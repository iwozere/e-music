import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../logic/blocs/audio_player_bloc.dart';
import '../../main.dart';

class MiniPlayer extends StatelessWidget {
  const MiniPlayer({super.key});

  @override
  Widget build(BuildContext context) {
    return BlocBuilder<AudioPlayerBloc, AudioPlayerState>(
      builder: (context, state) {
        if (state.currentTrack == null) return const SizedBox.shrink();

        return ValueListenableBuilder<String?>(
          valueListenable: NavigationService.currentRoute,
          builder: (context, currentRoute, _) {
            final isPlayerOpen = currentRoute == '/player';
            if (isPlayerOpen) return const SizedBox.shrink();

            return GestureDetector(
              onTap: () {
                MySpotifyApp.navigatorKey.currentState?.pushNamed('/player');
              },
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (state.errorMessage != null)
                    Container(
                      width: double.infinity,
                      color: Colors.red.withValues(alpha: 0.8),
                      padding: const EdgeInsets.symmetric(
                        vertical: 4,
                        horizontal: 8,
                      ),
                      child: Text(
                        state.errorMessage!,
                        style: const TextStyle(
                          fontSize: 10,
                          color: Colors.white,
                        ),
                        textAlign: TextAlign.center,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  // Seeker line
                  ClipRRect(
                    borderRadius: const BorderRadius.vertical(
                      top: Radius.circular(12),
                    ),
                    child: LinearProgressIndicator(
                      value: state.duration.inSeconds > 0
                          ? state.position.inSeconds / state.duration.inSeconds
                          : 0.0,
                      backgroundColor: Colors.white12,
                      valueColor: AlwaysStoppedAnimation<Color>(
                        Theme.of(context).primaryColor,
                      ),
                      minHeight: 3,
                    ),
                  ),
                  Container(
                    height: 67, // Total 70 including progress bar
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    decoration: BoxDecoration(
                      color: Theme.of(context).cardColor,
                      borderRadius: const BorderRadius.vertical(
                        bottom: Radius.circular(12),
                      ),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 45,
                          height: 45,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(6),
                            image: state.currentTrack!.thumbnail != null
                                ? DecorationImage(
                                    image: NetworkImage(
                                      state.currentTrack!.thumbnail!,
                                    ),
                                    fit: BoxFit.cover,
                                  )
                                : null,
                          ),
                          child: state.currentTrack!.thumbnail == null
                              ? const Icon(Icons.music_note)
                              : null,
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                state.currentTrack!.title,
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                              Row(
                                children: [
                                  Text(
                                    '${_formatDuration(state.position)} / ${_formatDuration(state.duration)}',
                                    style: TextStyle(
                                      color: Theme.of(context).primaryColor,
                                      fontSize: 10,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      state.currentTrack!.artist ??
                                          'Unknown Artist',
                                      style: const TextStyle(
                                        color: Colors.white70,
                                        fontSize: 10,
                                      ),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.skip_previous, size: 24),
                          onPressed: () {
                            context.read<AudioPlayerBloc>().add(
                              SkipPreviousEvent(),
                            );
                          },
                        ),
                        IconButton(
                          icon: Icon(
                            state.isPlaying ? Icons.pause : Icons.play_arrow,
                            size: 28,
                          ),
                          onPressed: () {
                            if (state.isPlaying) {
                              context.read<AudioPlayerBloc>().add(PauseTrack());
                            } else {
                              context.read<AudioPlayerBloc>().add(
                                ResumeTrack(),
                              );
                            }
                          },
                        ),
                        IconButton(
                          icon: const Icon(Icons.skip_next, size: 24),
                          onPressed: () {
                            context.read<AudioPlayerBloc>().add(
                              SkipNextEvent(),
                            );
                          },
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  String _formatDuration(Duration duration) {
    String twoDigits(int n) => n.toString().padLeft(2, "0");
    String twoDigitMinutes = twoDigits(duration.inMinutes.remainder(60));
    String twoDigitSeconds = twoDigits(duration.inSeconds.remainder(60));
    return "$twoDigitMinutes:$twoDigitSeconds";
  }
}
