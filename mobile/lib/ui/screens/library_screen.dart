import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../theme/app_colors.dart';
import '../../repositories/track_repository.dart';
import '../../models/track.dart';
import '../../logic/blocs/audio_player_bloc.dart';
import '../widgets/mini_player.dart';
import 'package:share_plus/share_plus.dart';

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  List<Map<String, dynamic>> _playlists = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadPlaylists();
  }

  Future<void> _loadPlaylists() async {
    final repository = context.read<TrackRepository>();
    final playlists = await repository.getPlaylists();
    if (mounted) {
      setState(() {
        _playlists = playlists;
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Your Library')),
      body: Stack(
        children: [
          _isLoading
              ? const Center(child: CircularProgressIndicator())
              : _playlists.isEmpty
              ? const Center(
                  child: Text('You haven\'t created any playlists yet.'),
                )
              : ListView.builder(
                  padding: const EdgeInsets.only(bottom: 100),
                  itemCount: _playlists.length,
                  itemBuilder: (context, index) {
                    final playlist = _playlists[index];
                    return ListTile(
                      leading: Container(
                        width: 50,
                        height: 50,
                        decoration: BoxDecoration(
                          color: AppColors.white.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Icon(
                          Icons.playlist_play,
                          color: AppColors.primary,
                        ),
                      ),
                      title: Text(playlist['name'] ?? 'Untitled Playlist'),
                      subtitle: const Text('Playlist'),
                      trailing: IconButton(
                        icon: const Icon(Icons.share),
                        onPressed: () {
                          Share.share(
                            'Check out my playlist "${playlist['name']}" on MySpotify: https://e-music.win/?playlist=${playlist['id']}',
                          );
                        },
                      ),
                      onTap: () {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => PlaylistDetailScreen(
                              playlistId: playlist['id'],
                              name: playlist['name'],
                            ),
                          ),
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

class PlaylistDetailScreen extends StatefulWidget {
  final String playlistId;
  final String name;

  const PlaylistDetailScreen({
    super.key,
    required this.playlistId,
    required this.name,
  });

  @override
  State<PlaylistDetailScreen> createState() => _PlaylistDetailScreenState();
}

class _PlaylistDetailScreenState extends State<PlaylistDetailScreen> {
  List<Track> _tracks = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadTracks();
  }

  Future<void> _loadTracks() async {
    final repository = context.read<TrackRepository>();
    final tracks = await repository.getPlaylistTracks(widget.playlistId);
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
      appBar: AppBar(title: Text(widget.name)),
      body: Stack(
        children: [
          _isLoading
              ? const Center(child: CircularProgressIndicator())
              : ListView.builder(
                  padding: const EdgeInsets.only(bottom: 100),
                  itemCount: _tracks.length,
                  itemBuilder: (context, index) {
                    final track = _tracks[index];
                    return ListTile(
                      leading: track.thumbnail != null
                          ? Image.network(
                              track.thumbnail!,
                              width: 40,
                              height: 40,
                              fit: BoxFit.cover,
                            )
                          : const Icon(Icons.music_note),
                      title: Text(track.title),
                      subtitle: Text(track.artist ?? 'Unknown Artist'),
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
