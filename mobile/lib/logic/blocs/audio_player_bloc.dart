import 'dart:async';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:just_audio/just_audio.dart';
import 'package:audio_service/audio_service.dart';
import '../audio_handler.dart';
import '../../models/track.dart';
import '../../repositories/track_repository.dart';

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

class AudioPlayerState {
  final Track? currentTrack;
  final List<Track> queue;
  final bool isPlaying;
  final Duration position;
  final Duration duration;
  final PlayerState playerState;
  final String? errorMessage;

  AudioPlayerState({
    this.currentTrack,
    this.queue = const [],
    this.isPlaying = false,
    this.position = Duration.zero,
    this.duration = Duration.zero,
    required this.playerState,
    this.errorMessage,
  });

  AudioPlayerState copyWith({
    Track? currentTrack,
    List<Track>? queue,
    bool? isPlaying,
    Duration? position,
    Duration? duration,
    PlayerState? playerState,
    String? errorMessage,
  }) {
    return AudioPlayerState(
      currentTrack: currentTrack ?? this.currentTrack,
      queue: queue ?? this.queue,
      isPlaying: isPlaying ?? this.isPlaying,
      position: position ?? this.position,
      duration: duration ?? this.duration,
      playerState: playerState ?? this.playerState,
      errorMessage: errorMessage,
    );
  }
}

class AudioPlayerBloc extends Bloc<AudioPlayerEvent, AudioPlayerState> {
  static const _lockChannel = MethodChannel('com.myspotify.mobile/locks');
  final MyAudioHandler audioHandler;
  final TrackRepository trackRepository;

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
      if (event.tracks.isNotEmpty) {
        emit(state.copyWith(queue: event.tracks, errorMessage: null));
        try {
          // Warm up DNS cache
          try {
            final uri = Uri.parse(trackRepository.apiClient.baseUrl);
            if (uri.hasAuthority) {
              _loggerInfo('Warming up DNS for ${uri.host}...');
              InternetAddress.lookup(uri.host)
                  .then((addresses) {
                    _loggerInfo(
                      'DNS lookup successful: ${addresses.length} addresses found.',
                    );
                  })
                  .catchError((e) {
                    _loggerError('DNS warm-up failed: $e');
                    return null;
                  });
            }
          } catch (e) {
            _loggerError('Failed to parse baseUrl for DNS warm-up: $e');
          }

          final sources = event.tracks.map((track) {
            final url = trackRepository.getStreamUrl(
              track.remoteId ?? track.id,
            );
            return AudioSource.uri(
              Uri.parse(url),
              tag: MediaItem(
                id: track.remoteId ?? track.id,
                album: 'Album',
                title: track.title,
                artist: track.artist,
                artUri: track.thumbnail != null
                    ? Uri.parse(track.thumbnail!)
                    : null,
              ),
            );
          }).toList();

          await audioHandler.stop();
          await _audioPlayer.setAudioSources(sources, preload: false);
          await audioHandler.play();

          emit(
            state.copyWith(currentTrack: event.tracks.first, isPlaying: true),
          );
        } catch (e) {
          _loggerError('Error playing playlist: $e');
          emit(state.copyWith(errorMessage: 'Playback error: $e'));
        }
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

    on<_UpdatePosition>((event, emit) {
      emit(state.copyWith(position: event.position));
    });

    on<_UpdateDuration>((event, emit) {
      emit(state.copyWith(duration: event.duration));
    });

    on<_UpdatePlayerState>((event, emit) {
      emit(
        state.copyWith(
          playerState: event.state,
          isPlaying: event.state.playing,
        ),
      );
    });

    on<_UpdateCurrentTrack>((event, emit) async {
      emit(state.copyWith(currentTrack: event.track));
      if (state.isPlaying) {
        await Future.delayed(const Duration(milliseconds: 300));
        audioHandler.play();
      }
    });

    on<_HandlePlaybackError>((event, emit) {
      emit(state.copyWith(errorMessage: 'Playback Error: ${event.message}'));
    });

    on<UpdateTrackLikedStatus>((event, emit) {
      if (state.currentTrack?.id == event.trackId) {
        final updatedTrack = state.currentTrack!.copyWith(
          isLiked: event.isLiked,
        );
        emit(state.copyWith(currentTrack: updatedTrack));
      }
    });
  }

  Future<void> _playTrack(Track track, Emitter<AudioPlayerState> emit) async {
    final url = trackRepository.getStreamUrl(track.remoteId ?? track.id);
    try {
      final source = AudioSource.uri(
        Uri.parse(url),
        tag: MediaItem(
          id: track.remoteId ?? track.id,
          album: 'Album',
          title: track.title,
          artist: track.artist,
          artUri: track.thumbnail != null ? Uri.parse(track.thumbnail!) : null,
        ),
      );
      await _audioPlayer.setAudioSource(source, preload: false);
      audioHandler.play();
      emit(
        state.copyWith(
          currentTrack: track,
          isPlaying: true,
          queue: [track],
          errorMessage: null,
        ),
      );
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
