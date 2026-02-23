import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../theme/app_colors.dart';
import '../../repositories/track_repository.dart';
import '../../models/track.dart';
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
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _playlists.isEmpty
          ? const Center(child: Text('You haven\'t created any playlists yet.'))
          : ListView.builder(
              padding: const EdgeInsets.only(bottom: 20),
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
                    child: Icon(Icons.playlist_play, color: AppColors.primary),
                  ),
                  title: Text(playlist['name'] ?? 'Untitled Playlist'),
                  subtitle: const Text('Playlist'),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.share),
                        onPressed: () {
                          Share.share(
                            'Check out my playlist "${playlist['name']}" on MySpotify: https://e-music.win/?playlist=${playlist['id']}',
                          );
                        },
                      ),
                      PopupMenuButton<String>(
                        icon: const Icon(Icons.more_vert),
                        onSelected: (value) async {
                          if (value == 'delete') {
                            final confirm = await showDialog<bool>(
                              context: context,
                              builder: (context) => AlertDialog(
                                title: const Text('Delete Playlist'),
                                content: Text(
                                  'Are you sure you want to delete "${playlist['name']}"?',
                                ),
                                actions: [
                                  TextButton(
                                    onPressed: () =>
                                        Navigator.pop(context, false),
                                    child: const Text('Cancel'),
                                  ),
                                  TextButton(
                                    onPressed: () =>
                                        Navigator.pop(context, true),
                                    child: const Text(
                                      'Delete',
                                      style: TextStyle(color: Colors.red),
                                    ),
                                  ),
                                ],
                              ),
                            );

                            if (confirm == true) {
                              if (!context.mounted) return;
                              final repository = context
                                  .read<TrackRepository>();
                              final messenger = ScaffoldMessenger.of(context);

                              final success = await repository.deletePlaylist(
                                playlist['id'],
                              );

                              if (success) {
                                messenger.showSnackBar(
                                  const SnackBar(
                                    content: Text('Playlist deleted'),
                                  ),
                                );
                                _loadPlaylists();
                              } else {
                                messenger.showSnackBar(
                                  const SnackBar(
                                    content: Text('Failed to delete playlist'),
                                  ),
                                );
                              }
                            }
                          }
                        },
                        itemBuilder: (context) => [
                          const PopupMenuItem(
                            value: 'delete',
                            child: Text(
                              'Delete Playlist',
                              style: TextStyle(color: Colors.red),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                  onTap: () async {
                    final navigator = Navigator.of(context);
                    await navigator.push(
                      MaterialPageRoute(
                        builder: (_) => PlaylistDetailScreen(
                          playlistId: playlist['id'],
                          name: playlist['name'],
                        ),
                      ),
                    );
                    _loadPlaylists(); // Refresh after coming back
                  },
                );
              },
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
          if (_tracks.isNotEmpty) ...[
            IconButton(
              icon: const Icon(Icons.shuffle),
              tooltip: 'Shuffle',
              onPressed: () {
                final shuffledTracks = List<Track>.from(_tracks)..shuffle();
                context.read<AudioPlayerBloc>().add(
                  PlayPlaylistEvent(shuffledTracks),
                );
              },
            ),
            IconButton(
              icon: const Icon(Icons.play_circle_fill),
              tooltip: 'Play All',
              onPressed: () {
                context.read<AudioPlayerBloc>().add(PlayPlaylistEvent(_tracks));
              },
            ),
          ],
          IconButton(
            icon: const Icon(Icons.delete_outline),
            tooltip: 'Delete Playlist',
            onPressed: () async {
              final confirm = await showDialog<bool>(
                context: context,
                builder: (context) => AlertDialog(
                  title: const Text('Delete Playlist'),
                  content: Text(
                    'Are you sure you want to delete "${widget.name}"?',
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Cancel'),
                    ),
                    TextButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text(
                        'Delete',
                        style: TextStyle(color: Colors.red),
                      ),
                    ),
                  ],
                ),
              );

              if (confirm == true) {
                if (!context.mounted) return;
                final repository = context.read<TrackRepository>();
                final navigator = Navigator.of(context);
                final messenger = ScaffoldMessenger.of(context);

                final success = await repository.deletePlaylist(
                  widget.playlistId,
                );

                if (success) {
                  navigator.pop();
                  messenger.showSnackBar(
                    const SnackBar(content: Text('Playlist deleted')),
                  );
                } else {
                  messenger.showSnackBar(
                    const SnackBar(content: Text('Failed to delete playlist')),
                  );
                }
              }
            },
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : ListView.builder(
              padding: const EdgeInsets.only(bottom: 20),
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
    );
  }
}
