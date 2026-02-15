import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../logic/blocs/audio_player_bloc.dart';
import '../screens/player_screen.dart';

class MiniPlayer extends StatelessWidget {
  const MiniPlayer({super.key});

  @override
  Widget build(BuildContext context) {
    return BlocBuilder<AudioPlayerBloc, AudioPlayerState>(
      builder: (context, state) {
        if (state.currentTrack == null) return const SizedBox.shrink();

        return GestureDetector(
          onTap: () {
            Navigator.of(
              context,
            ).push(MaterialPageRoute(builder: (_) => const PlayerScreen()));
          },
          child: Container(
            height: 70,
            margin: const EdgeInsets.all(8),
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: BoxDecoration(
              color: Theme.of(context).cardColor,
              borderRadius: BorderRadius.circular(12),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.5),
                  blurRadius: 10,
                  offset: const Offset(0, 5),
                ),
              ],
            ),
            child: Row(
              children: [
                Container(
                  width: 50,
                  height: 50,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(6),
                    image: state.currentTrack!.thumbnail != null
                        ? DecorationImage(
                            image: NetworkImage(state.currentTrack!.thumbnail!),
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
                        style: const TextStyle(fontWeight: FontWeight.bold),
                        overflow: TextOverflow.ellipsis,
                      ),
                      Text(
                        state.currentTrack!.artist ?? 'Unknown Artist',
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 12,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
                IconButton(
                  icon: Icon(state.isPlaying ? Icons.pause : Icons.play_arrow),
                  onPressed: () {
                    if (state.isPlaying) {
                      context.read<AudioPlayerBloc>().add(PauseTrack());
                    } else {
                      context.read<AudioPlayerBloc>().add(ResumeTrack());
                    }
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
