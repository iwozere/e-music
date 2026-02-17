import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../theme/app_colors.dart';
import '../../repositories/track_repository.dart';
import '../../models/track.dart';
import '../widgets/mini_player.dart';
import 'package:share_plus/share_plus.dart';
import '../widgets/track_list_tile.dart';
import '../../logic/blocs/audio_player_bloc.dart';

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

  void _showCreatePlaylistDialog() {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Create Playlist'),
          content: TextField(
            controller: controller,
            decoration: const InputDecoration(hintText: 'Playlist Name'),
            autofocus: true,
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () async {
                final name = controller.text.trim();
                if (name.isNotEmpty) {
                  final repository = context.read<TrackRepository>();
                  final success = await repository.createPlaylist(name);
                  if (context.mounted) {
                    Navigator.pop(context);
                    if (success) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text('Playlist "$name" created')),
                      );
                      _loadPlaylists();
                    } else {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('Failed to create playlist'),
                        ),
                      );
                    }
                  }
                }
              },
              child: const Text('Create'),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your Library'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add),
            onPressed: _showCreatePlaylistDialog,
          ),
        ],
      ),
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
      appBar: AppBar(
        title: Text(widget.name),
        actions: [
          if (_tracks.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.play_circle_fill),
              tooltip: 'Play All',
              onPressed: () {
                context.read<AudioPlayerBloc>().add(PlayPlaylistEvent(_tracks));
              },
            ),
        ],
      ),
      body: Stack(
        children: [
          _isLoading
              ? const Center(child: CircularProgressIndicator())
              : ListView.builder(
                  padding: const EdgeInsets.only(bottom: 100),
                  itemCount: _tracks.length,
                  itemBuilder: (context, index) {
                    final track = _tracks[index];
                    return TrackListTile(
                      track: track,
                      playlistId: widget.playlistId,
                      onRemove: _loadTracks,
                    );
                  },
                ),
          const Positioned(left: 0, right: 0, bottom: 0, child: MiniPlayer()),
        ],
      ),
    );
  }
}
