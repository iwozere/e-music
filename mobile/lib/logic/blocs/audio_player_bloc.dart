import 'dart:async';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:just_audio/just_audio.dart';
import 'package:audio_service/audio_service.dart';
import '../audio_handler.dart';
import '../../models/track.dart';
import '../../repositories/track_repository.dart';
import '../../services/download_service.dart';

// ─── Events ───────────────────────────────────────────────────────────────────

abstract class AudioPlayerEvent {}

class PlayTrackEvent extends AudioPlayerEvent {
  final Track track;
  PlayTrackEvent(this.track);
}

class AddToQueueEvent extends AudioPlayerEvent {
  final Track track;
  final bool playNext;
  AddToQueueEvent(this.track, {this.playNext = false});
}

class PlayNextInQueue extends AudioPlayerEvent {}

class PauseTrack extends AudioPlayerEvent {}

class ResumeTrack extends AudioPlayerEvent {}

class SkipNextEvent extends AudioPlayerEvent {}

class SkipPreviousEvent extends AudioPlayerEvent {}

class SeekTrackEvent extends AudioPlayerEvent {
  final Duration position;
  SeekTrackEvent(this.position);
}

class UpdateTrackLikedStatus extends AudioPlayerEvent {
  final String trackId;
  final bool isLiked;
  UpdateTrackLikedStatus(this.trackId, this.isLiked);
}

class PlayPlaylistEvent extends AudioPlayerEvent {
  final List<Track> tracks;
  PlayPlaylistEvent(this.tracks);
}

/// Fetch AI suggestions and play them as the next queue.
class TriggerAiShuffleEvent extends AudioPlayerEvent {}

/// Queue server-side library import and download to device local storage.
class SaveTrackToLibraryEvent extends AudioPlayerEvent {
  final Track track;
  SaveTrackToLibraryEvent(this.track);
}

// Internal events — not exposed to UI
class _UpdatePosition extends AudioPlayerEvent {
  final Duration position;
  _UpdatePosition(this.position);
}

class _UpdateDuration extends AudioPlayerEvent {
  final Duration duration;
  _UpdateDuration(this.duration);
}

class _UpdatePlayerState extends AudioPlayerEvent {
  final PlayerState state;
  _UpdatePlayerState(this.state);
}

class _UpdateCurrentTrack extends AudioPlayerEvent {
  final Track track;
  _UpdateCurrentTrack(this.track);
}

class _HandlePlaybackError extends AudioPlayerEvent {
  final String message;
  _HandlePlaybackError(this.message);
}

class _TrackSavedLocally extends AudioPlayerEvent {
  final String trackId;
  final String localPath;
  _TrackSavedLocally(this.trackId, this.localPath);
}

// ─── State ────────────────────────────────────────────────────────────────────

class AudioPlayerState {
  final Track? currentTrack;
  final List<Track> queue;
  final bool isPlaying;
  final Duration position;
  final Duration duration;
  final PlayerState playerState;
  final String? errorMessage;
  final bool isAiShuffling;
  final bool isSavingToLibrary;

  AudioPlayerState({
    this.currentTrack,
    this.queue = const [],
    this.isPlaying = false,
    this.position = Duration.zero,
    this.duration = Duration.zero,
    required this.playerState,
    this.errorMessage,
    this.isAiShuffling = false,
    this.isSavingToLibrary = false,
  });

  AudioPlayerState copyWith({
    Track? currentTrack,
    List<Track>? queue,
    bool? isPlaying,
    Duration? position,
    Duration? duration,
    PlayerState? playerState,
    String? errorMessage,
    bool? isAiShuffling,
    bool? isSavingToLibrary,
  }) {
    return AudioPlayerState(
      currentTrack: currentTrack ?? this.currentTrack,
      queue: queue ?? this.queue,
      isPlaying: isPlaying ?? this.isPlaying,
      position: position ?? this.position,
      duration: duration ?? this.duration,
      playerState: playerState ?? this.playerState,
      errorMessage: errorMessage,
      isAiShuffling: isAiShuffling ?? this.isAiShuffling,
      isSavingToLibrary: isSavingToLibrary ?? this.isSavingToLibrary,
    );
  }
}

// ─── Bloc ─────────────────────────────────────────────────────────────────────

class AudioPlayerBloc extends Bloc<AudioPlayerEvent, AudioPlayerState> {
  static const _lockChannel = MethodChannel('com.myspotify.mobile/locks');
  final MyAudioHandler audioHandler;
  final TrackRepository trackRepository;

  // Guards against duplicate TriggerAiShuffleEvent from rapid `completed` stream events.
  // Checked synchronously in the stream listener (before BLoC state can update).
  bool _aiShufflePending = false;

  // True while PlayPlaylistEvent is loading new sources. Prevents _UpdateCurrentTrack
  // from calling play() during the load (which would race with PlayPlaylistEvent's own
  // play() and produce two concurrent stream requests for the same track).
  bool _playlistLoading = false;

  AudioPlayer get _audioPlayer => audioHandler.player;

  AudioPlayerBloc({
    required TrackRepository repository,
    required this.audioHandler,
  }) : trackRepository = repository,
       super(
         AudioPlayerState(
           playerState: PlayerState(false, ProcessingState.idle),
         ),
       ) {
    _audioPlayer.setVolume(1.0);

    _audioPlayer.positionStream.listen((pos) {
      add(_UpdatePosition(pos));
    });

    _audioPlayer.durationStream.listen((dur) {
      add(_UpdateDuration(dur ?? Duration.zero));
    });

    _audioPlayer.playerStateStream.listen((playerState) {
      _loggerInfo(
        'ProcessingState: ${playerState.processingState}, Playback: ${playerState.playing}',
      );
      add(_UpdatePlayerState(playerState));

      if (playerState.playing) {
        _acquireLocks();
      } else if (playerState.processingState == ProcessingState.idle ||
          playerState.processingState == ProcessingState.completed) {
        _releaseLocks();
      }

      // Auto-trigger AI shuffle when the queue is exhausted.
      // Use _aiShufflePending (synchronous flag) instead of state.isAiShuffling
      // because BLoC state may not have updated yet when this fires.
      if (playerState.processingState == ProcessingState.completed &&
          !_audioPlayer.hasNext &&
          !_aiShufflePending) {
        _aiShufflePending = true;
        add(TriggerAiShuffleEvent());
      }
    });

    _audioPlayer.currentIndexStream.listen((index) {
      if (index != null &&
          state.queue.isNotEmpty &&
          index < state.queue.length) {
        add(_UpdateCurrentTrack(state.queue[index]));
      }
    });

    _audioPlayer.playbackEventStream.listen(
      (event) {
        _loggerInfo('Playback event: ${event.processingState}');
      },
      onError: (Object e, StackTrace st) {
        _loggerError('Playback stream error: $e');
        add(_HandlePlaybackError(e.toString()));
      },
    );

    on<PlayTrackEvent>((event, emit) async {
      await _playTrack(event.track, emit);
    });

    on<AddToQueueEvent>((event, emit) {
      final newQueue = List<Track>.from(state.queue);
      if (event.playNext) {
        newQueue.insert(0, event.track);
      } else {
        newQueue.add(event.track);
      }
      emit(state.copyWith(queue: newQueue));
    });

    on<PlayPlaylistEvent>((event, emit) async {
      if (event.tracks.isEmpty) return;
      // Hold both guards while we stop the old player and load new sources:
      // • _aiShufflePending: stop() briefly emits `completed` which would re-trigger AI shuffle
      // • _playlistLoading: prevents _UpdateCurrentTrack from calling play() during load,
      //   which would race with our own play() and produce duplicate stream requests.
      _aiShufflePending = true;
      _playlistLoading = true;
      // Queue is updated again after URL resolution to reflect any dropped tracks
      emit(state.copyWith(queue: event.tracks, errorMessage: null));
      try {
        // DNS warm-up
        try {
          final uri = Uri.parse(trackRepository.apiClient.baseUrl);
          if (uri.hasAuthority) {
            _loggerInfo('Warming up DNS for ${uri.host}...');
            InternetAddress.lookup(uri.host)
                .then((_) {})
                .catchError((_) => null);
          }
        } catch (_) {}

        // Fetch stream URLs only for tracks without a valid local file.
        // Catch individual failures so one bad track doesn't abort the whole playlist.
        final urls = List<String?>.filled(event.tracks.length, null);
        await Future.wait([
          for (int i = 0; i < event.tracks.length; i++)
            () async {
              final track = event.tracks[i];
              final hasLocal = track.localPath != null &&
                  File(track.localPath!).existsSync();
              if (!hasLocal) {
                try {
                  urls[i] = await trackRepository
                      .getStreamUrl(track.remoteId ?? track.id);
                } catch (e) {
                  _loggerError('URL fetch failed for ${track.id}: $e');
                }
              }
            }(),
        ]);

        // Drop tracks whose URL could not be resolved (no local file, no stream URL)
        final validEntries = <({Track track, String? url})>[];
        for (int i = 0; i < event.tracks.length; i++) {
          final track = event.tracks[i];
          final hasLocal = track.localPath != null &&
              File(track.localPath!).existsSync();
          if (hasLocal || urls[i] != null) {
            validEntries.add((track: track, url: urls[i]));
          }
        }
        if (validEntries.isEmpty) throw Exception('No playable tracks in playlist');

        final sources = validEntries.map((e) {
          final tag = MediaItem(
            id: e.track.remoteId ?? e.track.id,
            album: e.track.album ?? 'Album',
            title: e.track.title,
            artist: e.track.artist,
            artUri: e.track.thumbnail != null
                ? Uri.parse(e.track.thumbnail!)
                : null,
          );
          final hasLocal = e.track.localPath != null &&
              File(e.track.localPath!).existsSync();
          if (hasLocal) {
            return AudioSource.file(e.track.localPath!, tag: tag);
          }
          return AudioSource.uri(Uri.parse(e.url!), tag: tag);
        }).toList();

        await audioHandler.stop();
        await _audioPlayer.setAudioSources(sources, preload: false);
        await audioHandler.play();

        final playableTracks = validEntries.map((e) => e.track).toList();
        emit(state.copyWith(
          queue: playableTracks,
          currentTrack: playableTracks.first,
          isPlaying: true,
        ));
      } catch (e) {
        _loggerError('Error playing playlist: $e');
        emit(state.copyWith(errorMessage: 'Playback error: $e'));
      } finally {
        _playlistLoading = false;
        _aiShufflePending = false;
      }
    });

    on<PlayNextInQueue>((event, emit) async {
      if (_audioPlayer.hasNext) {
        await audioHandler.skipToNext();
      }
    });

    on<SkipNextEvent>((event, emit) async {
      if (_audioPlayer.hasNext) {
        await audioHandler.skipToNext();
      }
    });

    on<SkipPreviousEvent>((event, emit) async {
      if (_audioPlayer.hasPrevious) {
        await audioHandler.skipToPrevious();
      }
    });

    on<PauseTrack>((event, emit) {
      audioHandler.pause();
      emit(state.copyWith(isPlaying: false));
    });

    on<ResumeTrack>((event, emit) {
      audioHandler.play();
      emit(state.copyWith(isPlaying: true));
    });

    on<SeekTrackEvent>((event, emit) {
      audioHandler.seek(event.position);
    });

    on<TriggerAiShuffleEvent>((event, emit) async {
      if (state.isAiShuffling) return;

      final token = await trackRepository.apiClient.getToken();
      if (token == null) {
        _aiShufflePending = false;
        emit(state.copyWith(errorMessage: 'login_required'));
        return;
      }

      emit(state.copyWith(isAiShuffling: true, errorMessage: null));
      try {
        // Build context from current track + queue
        final contextIds = <String>[];
        if (state.currentTrack != null) {
          contextIds.add(state.currentTrack!.remoteId ?? state.currentTrack!.id);
        }
        for (final t in state.queue) {
          final id = t.remoteId ?? t.id;
          if (!contextIds.contains(id)) contextIds.add(id);
        }

        final suggestions = await trackRepository.getAiShuffle(contextIds);
        if (suggestions.isEmpty) {
          emit(state.copyWith(
            isAiShuffling: false,
            errorMessage: 'AI shuffle returned no tracks',
          ));
          return;
        }

        emit(state.copyWith(isAiShuffling: false));
        add(PlayPlaylistEvent(suggestions));
      } catch (e) {
        _loggerError('AI shuffle failed: $e');
        emit(state.copyWith(
          isAiShuffling: false,
          errorMessage: 'AI shuffle failed: $e',
        ));
      } finally {
        _aiShufflePending = false;
      }
    });

    on<SaveTrackToLibraryEvent>((event, emit) async {
      if (state.isSavingToLibrary) return;
      emit(state.copyWith(isSavingToLibrary: true, errorMessage: null));
      try {
        // 1. Queue server-side library import (fire-and-forget, best effort)
        await trackRepository.saveToLibrary(event.track.id);

        // 2. Get a signed stream URL and download the audio to device storage
        final streamUrl = await trackRepository.getStreamUrl(
          event.track.remoteId ?? event.track.id,
        );
        final localPath = await DownloadService.downloadTrack(
          trackId: event.track.id,
          streamUrl: streamUrl,
        );

        if (localPath != null) {
          add(_TrackSavedLocally(event.track.id, localPath));
        }
        emit(state.copyWith(isSavingToLibrary: false));
      } catch (e) {
        _loggerError('Save to library failed: $e');
        emit(state.copyWith(
          isSavingToLibrary: false,
          errorMessage: 'Save failed: $e',
        ));
      }
    });

    on<_TrackSavedLocally>((event, emit) {
      // Update current track's localPath so subsequent plays use the local file
      if (state.currentTrack?.id == event.trackId) {
        final updated = state.currentTrack!.copyWith(localPath: event.localPath);
        emit(state.copyWith(currentTrack: updated));
      }
    });

    on<_UpdatePosition>((event, emit) {
      emit(state.copyWith(position: event.position));
    });

    on<_UpdateDuration>((event, emit) {
      emit(state.copyWith(duration: event.duration));
    });

    on<_UpdatePlayerState>((event, emit) {
      emit(state.copyWith(
        playerState: event.state,
        isPlaying: event.state.playing,
      ));
    });

    on<_UpdateCurrentTrack>((event, emit) async {
      emit(state.copyWith(currentTrack: event.track));
      // Re-trigger play() when advancing between tracks, but not while
      // PlayPlaylistEvent is still loading sources (_playlistLoading guard).
      // Without this call some Android setups pause between tracks.
      if (state.isPlaying && !_playlistLoading) {
        await Future.delayed(const Duration(milliseconds: 300));
        audioHandler.play();
      }
    });

    on<_HandlePlaybackError>((event, emit) {
      emit(state.copyWith(errorMessage: 'Playback Error: ${event.message}'));
    });

    on<UpdateTrackLikedStatus>((event, emit) {
      if (state.currentTrack?.id == event.trackId) {
        final updatedTrack = state.currentTrack!.copyWith(isLiked: event.isLiked);
        emit(state.copyWith(currentTrack: updatedTrack));
      }
    });
  }

  Future<void> _playTrack(Track track, Emitter<AudioPlayerState> emit) async {
    try {
      final AudioSource source;

      // Local-first: use device file when available, fall back to server stream
      final localFile = track.localPath != null ? File(track.localPath!) : null;
      if (localFile != null && localFile.existsSync()) {
        _loggerInfo('Playing from local file: ${track.localPath}');
        source = AudioSource.file(
          track.localPath!,
          tag: MediaItem(
            id: track.id,
            album: track.album ?? 'Album',
            title: track.title,
            artist: track.artist,
            artUri: track.thumbnail != null ? Uri.parse(track.thumbnail!) : null,
          ),
        );
      } else {
        final url = await trackRepository.getStreamUrl(track.remoteId ?? track.id);
        source = AudioSource.uri(
          Uri.parse(url),
          tag: MediaItem(
            id: track.remoteId ?? track.id,
            album: track.album ?? 'Album',
            title: track.title,
            artist: track.artist,
            artUri: track.thumbnail != null ? Uri.parse(track.thumbnail!) : null,
          ),
        );
      }

      await _audioPlayer.setAudioSource(source, preload: false);
      audioHandler.play();
      emit(state.copyWith(
        currentTrack: track,
        isPlaying: true,
        queue: [track],
        errorMessage: null,
      ));
      trackRepository.playTrack(track.id);
    } catch (e) {
      _loggerError('Error playing track ${track.id}: $e');
      emit(state.copyWith(errorMessage: 'Playback error: $e'));
    }
  }

  Future<void> _acquireLocks() async {
    try {
      await _lockChannel.invokeMethod('acquireLocks');
      _loggerInfo('Native locks acquired.');
    } catch (e) {
      _loggerError('Failed to acquire native locks: $e');
    }
  }

  Future<void> _releaseLocks() async {
    try {
      await _lockChannel.invokeMethod('releaseLocks');
      _loggerInfo('Native locks released.');
    } catch (e) {
      _loggerError('Failed to release native locks: $e');
    }
  }

  void _loggerInfo(String message) {
    // ignore: avoid_print
    print('MYSPOTIFY_INFO: $message');
  }

  void _loggerError(String message) {
    // ignore: avoid_print
    print('MYSPOTIFY_ERROR: $message');
  }

  @override
  Future<void> close() {
    _releaseLocks();
    return super.close();
  }
}
