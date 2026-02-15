import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../models/track.dart';
import '../../repositories/track_repository.dart';
import '../../logic/blocs/audio_player_bloc.dart';
import '../widgets/mini_player.dart';
import 'package:share_plus/share_plus.dart';

class LikedSongsScreen extends StatefulWidget {
  const LikedSongsScreen({super.key});

  @override
  State<LikedSongsScreen> createState() => _LikedSongsScreenState();
}

class _LikedSongsScreenState extends State<LikedSongsScreen> {
  List<Track> _tracks = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadLikedTracks();
  }

  Future<void> _loadLikedTracks() async {
    final repository = context.read<TrackRepository>();
    final tracks = await repository.getLikedTracks();
    if (mounted) {
      setState(() {
        _tracks = tracks;
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Liked Songs'),
        actions: [
          IconButton(
            icon: const Icon(Icons.share),
            onPressed: () {
              Share.share(
                'Check out my liked songs on MySpotify: https://api.e-music.win/tracks/liked',
              );
            },
          ),
        ],
      ),
      body: Stack(
        children: [
          _isLoading
              ? const Center(child: CircularProgressIndicator())
              : _tracks.isEmpty
              ? const Center(child: Text('No liked songs yet!'))
              : ListView.builder(
                  padding: const EdgeInsets.only(bottom: 100),
                  itemCount: _tracks.length,
                  itemBuilder: (context, index) {
                    final track = _tracks[index];
                    return ListTile(
                      leading: track.thumbnail != null
                          ? ClipRRect(
                              borderRadius: BorderRadius.circular(4),
                              child: Image.network(
                                track.thumbnail!,
                                width: 50,
                                height: 50,
                                fit: BoxFit.cover,
                              ),
                            )
                          : const Icon(Icons.music_note),
                      title: Text(track.title),
                      subtitle: Text(track.artist ?? 'Unknown Artist'),
                      trailing: IconButton(
                        icon: const Icon(Icons.favorite, color: Colors.red),
                        onPressed: () async {
                          await context.read<TrackRepository>().likeTrack(
                            track.id,
                            isLiked: false,
                          );
                          _loadLikedTracks();
                        },
                      ),
                      onTap: () {
                        context.read<AudioPlayerBloc>().add(
                          PlayTrackEvent(track),
                        );
                      },
                    );
                  },
                ),
          const Positioned(left: 0, right: 0, bottom: 0, child: MiniPlayer()),
        ],
      ),
    );
  }
}
