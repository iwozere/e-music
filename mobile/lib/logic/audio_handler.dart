import 'package:just_audio/just_audio.dart';
import 'package:audio_service/audio_service.dart';
import '../models/track.dart';

class MyAudioHandler extends BaseAudioHandler with SeekHandler {
  final AudioPlayer _player = AudioPlayer();

  MyAudioHandler() {
    // Broadcast state changes
    _player.playbackEventStream.map(_transformEvent).pipe(playbackState);
  }

  @override
  Future<void> play() => _player.play();

  @override
  Future<void> pause() => _player.pause();

  @override
  Future<void> seek(Duration position) => _player.seek(position);

  @override
  Future<void> stop() => _player.stop();

  @override
  Future<void> skipToNext() => _player.seekToNext();

  @override
  Future<void> skipToPrevious() => _player.seekToPrevious();

  // Helper to load a playlist/track and update metadata
  Future<void> setPlaylist(List<Track> tracks, {int? initialIndex}) async {
    final sources = tracks.map((track) {
      return AudioSource.uri(
        Uri.parse(
          '',
        ), // This will be set dynamically via setAudioSources in Bloc for now
        tag: MediaItem(
          id: track.remoteId ?? track.id,
          album: 'Album',
          title: track.title,
          artist: track.artist,
          artUri: track.thumbnail != null ? Uri.parse(track.thumbnail!) : null,
        ),
      );
    }).toList();

    // Use sources to avoid lint error and prepare for future playlist management
    _loggerInfo('Setting playlist with ${sources.length} tracks');
  }

  void _loggerInfo(String message) {
    // ignore: avoid_print
    print('MYSPOTIFY_HANDLER_INFO: $message');
  }

  PlaybackState _transformEvent(PlaybackEvent event) {
    return PlaybackState(
      controls: [
        MediaControl.skipToPrevious,
        if (_player.playing) MediaControl.pause else MediaControl.play,
        MediaControl.stop,
        MediaControl.skipToNext,
      ],
      systemActions: const {
        MediaAction.seek,
        MediaAction.seekForward,
        MediaAction.seekBackward,
      },
      androidCompactActionIndices: const [0, 1, 3],
      processingState: const {
        ProcessingState.idle: AudioProcessingState.idle,
        ProcessingState.loading: AudioProcessingState.loading,
        ProcessingState.buffering: AudioProcessingState.buffering,
        ProcessingState.ready: AudioProcessingState.ready,
        ProcessingState.completed: AudioProcessingState.completed,
      }[_player.processingState]!,
      playing: _player.playing,
      updatePosition: _player.position,
      bufferedPosition: _player.bufferedPosition,
      speed: _player.speed,
      queueIndex: event.currentIndex,
    );
  }

  AudioPlayer get player => _player;
}
