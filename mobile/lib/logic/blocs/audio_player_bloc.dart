import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:just_audio/just_audio.dart';
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

  AudioPlayerState({
    this.currentTrack,
    this.queue = const [],
    this.isPlaying = false,
    this.position = Duration.zero,
    this.duration = Duration.zero,
    required this.playerState,
  });

  AudioPlayerState copyWith({
    Track? currentTrack,
    List<Track>? queue,
    bool? isPlaying,
    Duration? position,
    Duration? duration,
    PlayerState? playerState,
  }) {
    return AudioPlayerState(
      currentTrack: currentTrack ?? this.currentTrack,
      queue: queue ?? this.queue,
      isPlaying: isPlaying ?? this.isPlaying,
      position: position ?? this.position,
      duration: duration ?? this.duration,
      playerState: playerState ?? this.playerState,
    );
  }
}

class AudioPlayerBloc extends Bloc<AudioPlayerEvent, AudioPlayerState> {
  final AudioPlayer _audioPlayer = AudioPlayer();
  final TrackRepository trackRepository;

  AudioPlayerBloc({required TrackRepository repository})
    : trackRepository = repository,
      super(
        AudioPlayerState(playerState: PlayerState(false, ProcessingState.idle)),
      ) {
    _audioPlayer.positionStream.listen((pos) {
      add(_UpdatePosition(pos));
    });

    _audioPlayer.durationStream.listen((dur) {
      add(_UpdateDuration(dur ?? Duration.zero));
    });

    _audioPlayer.playerStateStream.listen((playerState) {
      add(_UpdatePlayerState(playerState));
      // Auto play next if finished
      if (playerState.processingState == ProcessingState.completed) {
        add(PlayNextInQueue());
      }
    });

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
        final firstTrack = event.tracks.first;
        final remainingTracks = List<Track>.from(event.tracks)..removeAt(0);
        emit(state.copyWith(queue: remainingTracks));
        await _playTrack(firstTrack, emit);
      }
    });

    on<PlayNextInQueue>((event, emit) async {
      if (state.queue.isNotEmpty) {
        final nextTrack = state.queue.first;
        final newQueue = List<Track>.from(state.queue)..removeAt(0);
        emit(state.copyWith(queue: newQueue));
        await _playTrack(nextTrack, emit);
      }
    });

    on<PauseTrack>((event, emit) {
      _audioPlayer.pause();
      emit(state.copyWith(isPlaying: false));
    });

    on<ResumeTrack>((event, emit) {
      _audioPlayer.play();
      emit(state.copyWith(isPlaying: true));
    });

    on<SeekTrackEvent>((event, emit) {
      _audioPlayer.seek(event.position);
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
      await _audioPlayer.setUrl(url);
      _audioPlayer.play();
      emit(state.copyWith(currentTrack: track, isPlaying: true));
      trackRepository.playTrack(track.id); // fire and forget record play
    } catch (e) {
      // Log error properly
    }
  }

  @override
  Future<void> close() {
    _audioPlayer.dispose();
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
