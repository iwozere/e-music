import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../theme/app_colors.dart';
import '../../logic/blocs/audio_player_bloc.dart';
import '../../repositories/track_repository.dart';

class PlayerScreen extends StatelessWidget {
  const PlayerScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.keyboard_arrow_down, size: 30),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: const Text('Now Playing', style: TextStyle(fontSize: 16)),
        centerTitle: true,
      ),
      body: BlocBuilder<AudioPlayerBloc, AudioPlayerState>(
        builder: (context, state) {
          if (state.currentTrack == null) {
            return const Center(child: Text('No track playing'));
          }

          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Artwork
                AspectRatio(
                  aspectRatio: 1,
                  child: Container(
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(20),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(alpha: 0.5),
                          blurRadius: 30,
                          spreadRadius: 5,
                          offset: const Offset(0, 10),
                        ),
                      ],
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
                        ? const Icon(
                            Icons.music_note,
                            size: 100,
                            color: Colors.white24,
                          )
                        : null,
                  ),
                ),
                const SizedBox(height: 48),

                // Track Info
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            state.currentTrack!.title,
                            style: const TextStyle(
                              fontSize: 24,
                              fontWeight: FontWeight.bold,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                          Text(
                            state.currentTrack!.artist ?? 'Unknown Artist',
                            style: const TextStyle(
                              fontSize: 18,
                              color: Colors.white70,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: Icon(
                        state.currentTrack!.isLiked
                            ? Icons.favorite
                            : Icons.favorite_border,
                        color: state.currentTrack!.isLiked
                            ? Colors.red
                            : Colors.white70,
                      ),
                      onPressed: () {
                        context.read<TrackRepository>().likeTrack(
                          state.currentTrack!.id,
                          isLiked: !state.currentTrack!.isLiked,
                        );
                        // We should ideally fire an event to update the track in Bloc
                        context.read<AudioPlayerBloc>().add(
                          UpdateTrackLikedStatus(
                            state.currentTrack!.id,
                            !state.currentTrack!.isLiked,
                          ),
                        );
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 32),

                // Progress Bar
                Column(
                  children: [
                    SliderTheme(
                      data: SliderTheme.of(context).copyWith(
                        trackHeight: 4,
                        thumbShape: const RoundSliderThumbShape(
                          enabledThumbRadius: 6,
                        ),
                        overlayShape: const RoundSliderOverlayShape(
                          overlayRadius: 14,
                        ),
                        activeTrackColor: Theme.of(context).primaryColor,
                        inactiveTrackColor: Colors.white24,
                        thumbColor: Colors.white,
                      ),
                      child: Slider(
                        value: state.position.inSeconds.toDouble(),
                        max: state.duration.inSeconds.toDouble().clamp(
                          0.1,
                          double.infinity,
                        ),
                        onChanged: (value) {
                          context.read<AudioPlayerBloc>().add(
                            SeekTrackEvent(Duration(seconds: value.toInt())),
                          );
                        },
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            _formatDuration(state.position),
                            style: const TextStyle(
                              color: Colors.white70,
                              fontSize: 12,
                            ),
                          ),
                          Text(
                            _formatDuration(state.duration),
                            style: const TextStyle(
                              color: Colors.white70,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 32),

                // Controls
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    IconButton(
                      icon: const Icon(Icons.shuffle, color: Colors.white70),
                      onPressed: () {},
                    ),
                    IconButton(
                      icon: const Icon(Icons.skip_previous, size: 36),
                      onPressed: () {
                        context.read<AudioPlayerBloc>().add(
                          SkipPreviousEvent(),
                        );
                      },
                    ),
                    Container(
                      decoration: const BoxDecoration(
                        shape: BoxShape.circle,
                        color: Colors.white,
                      ),
                      child: IconButton(
                        icon: Icon(
                          state.isPlaying ? Icons.pause : Icons.play_arrow,
                          size: 36,
                          color: Colors.black,
                        ),
                        onPressed: () {
                          if (state.isPlaying) {
                            context.read<AudioPlayerBloc>().add(PauseTrack());
                          } else {
                            context.read<AudioPlayerBloc>().add(ResumeTrack());
                          }
                        },
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.skip_next, size: 36),
                      onPressed: () {
                        context.read<AudioPlayerBloc>().add(SkipNextEvent());
                      },
                    ),
                    IconButton(
                      icon: const Icon(Icons.repeat, color: Colors.white70),
                      onPressed: () {},
                    ),
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  String _formatDuration(Duration duration) {
    String twoDigits(int n) => n.toString().padLeft(2, "0");
    String twoDigitMinutes = twoDigits(duration.inMinutes.remainder(60));
    String twoDigitSeconds = twoDigits(duration.inSeconds.remainder(60));
    return "$twoDigitMinutes:$twoDigitSeconds";
  }
}
