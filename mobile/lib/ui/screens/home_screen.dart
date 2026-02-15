import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../../logic/blocs/audio_player_bloc.dart';
import '../../logic/blocs/search_bloc.dart';
import '../../models/track.dart';
import '../widgets/mini_player.dart';
import 'library_screen.dart';
import 'liked_songs_screen.dart';
import 'package:share_plus/share_plus.dart';
import '../../repositories/track_repository.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentIndex = 0;

  final List<Widget> _screens = [
    const _SearchView(),
    const LibraryScreen(),
    const LikedSongsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _screens[_currentIndex],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) => setState(() => _currentIndex = index),
        backgroundColor: Theme.of(context).primaryColor.withValues(alpha: 0.05),
        selectedItemColor: Theme.of(context).primaryColor,
        unselectedItemColor: Colors.white70,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.search), label: 'Search'),
          BottomNavigationBarItem(
            icon: Icon(Icons.library_music),
            label: 'Library',
          ),
          BottomNavigationBarItem(icon: Icon(Icons.favorite), label: 'Liked'),
        ],
      ),
    );
  }
}

class _SearchView extends StatefulWidget {
  const _SearchView();

  @override
  State<_SearchView> createState() => _SearchViewState();
}

class _SearchViewState extends State<_SearchView> {
  final TextEditingController _searchController = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('MySpotify'),
        actions: [
          IconButton(icon: const Icon(Icons.settings), onPressed: () {}),
        ],
      ),
      body: Stack(
        children: [
          Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(16.0),
                child: TextField(
                  controller: _searchController,
                  decoration: InputDecoration(
                    hintText: 'Search for tracks...',
                    prefixIcon: const Icon(Icons.search),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.05),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(30),
                      borderSide: BorderSide.none,
                    ),
                  ),
                  onChanged: (value) {
                    context.read<SearchBloc>().add(SearchQueryChanged(value));
                  },
                ),
              ),
              Expanded(
                child: BlocBuilder<SearchBloc, SearchState>(
                  builder: (context, state) {
                    if (state is SearchLoading) {
                      return const Center(child: CircularProgressIndicator());
                    } else if (state is SearchSuccess) {
                      return ListView.builder(
                        itemCount: state.tracks.length,
                        itemBuilder: (context, index) {
                          final track = state.tracks[index];
                          return _TrackListTile(track: track);
                        },
                      );
                    } else if (state is SearchInitial) {
                      return const Center(
                        child: Text('Start searching for music!'),
                      );
                    } else if (state is SearchFailure) {
                      return Center(child: Text('Error: ${state.error}'));
                    }
                    return Container();
                  },
                ),
              ),
              const SizedBox(height: 80), // Space for mini player
            ],
          ),
          const Positioned(left: 0, right: 0, bottom: 0, child: MiniPlayer()),
        ],
      ),
    );
  }
}

class _TrackListTile extends StatelessWidget {
  final Track track;
  const _TrackListTile({required this.track});

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Container(
        width: 50,
        height: 50,
        decoration: BoxDecoration(
          color: Colors.grey.withValues(alpha: 0.2),
          borderRadius: BorderRadius.circular(8),
          image: track.thumbnail != null
              ? DecorationImage(
                  image: NetworkImage(track.thumbnail!),
                  fit: BoxFit.cover,
                )
              : null,
        ),
        child: track.thumbnail == null ? const Icon(Icons.music_note) : null,
      ),
      title: Text(
        track.title,
        style: const TextStyle(fontWeight: FontWeight.bold),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Text(
        track.artist ?? 'Unknown Artist',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: PopupMenuButton<String>(
        icon: const Icon(Icons.more_vert),
        onSelected: (value) async {
          final trackRepo = context.read<TrackRepository>();
          final audioBloc = context.read<AudioPlayerBloc>();

          switch (value) {
            case 'like':
              await trackRepo.likeTrack(track.id, isLiked: !track.isLiked);
              audioBloc.add(UpdateTrackLikedStatus(track.id, !track.isLiked));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(
                      track.isLiked ? 'Removed from Likes' : 'Added to Likes',
                    ),
                  ),
                );
                // Trigger a refresh if on Liked screen? This is static in _SearchView though.
              }
              break;
            case 'queue':
              audioBloc.add(AddToQueueEvent(track));
              if (context.mounted) {
                ScaffoldMessenger.of(
                  context,
                ).showSnackBar(const SnackBar(content: Text('Added to Queue')));
              }
              break;
            case 'playlist':
              _showPlaylistSheet(context, track);
              break;
            case 'share':
              Share.share(
                'Listen to ${track.title} by ${track.artist} on MySpotify: https://e-music.win/?track=${track.id}',
              );
              break;
          }
        },
        itemBuilder: (context) => [
          PopupMenuItem(
            value: 'like',
            child: Row(
              children: [
                Icon(
                  track.isLiked ? Icons.favorite : Icons.favorite_border,
                  color: track.isLiked ? Colors.red : null,
                ),
                const SizedBox(width: 8),
                Text(track.isLiked ? 'Unlike' : 'Like'),
              ],
            ),
          ),
          const PopupMenuItem(
            value: 'queue',
            child: Row(
              children: [
                Icon(Icons.queue_music),
                SizedBox(width: 8),
                Text('Add to Queue'),
              ],
            ),
          ),
          const PopupMenuItem(
            value: 'playlist',
            child: Row(
              children: [
                Icon(Icons.playlist_add),
                SizedBox(width: 8),
                Text('Add to Playlist'),
              ],
            ),
          ),
          const PopupMenuItem(
            value: 'share',
            child: Row(
              children: [Icon(Icons.share), SizedBox(width: 8), Text('Share')],
            ),
          ),
        ],
      ),
      onTap: () {
        context.read<AudioPlayerBloc>().add(PlayTrackEvent(track));
      },
    );
  }

  void _showPlaylistSheet(BuildContext context, Track track) {
    showModalBottomSheet(
      context: context,
      builder: (context) {
        final trackRepo = context.read<TrackRepository>();
        return FutureBuilder<List<Map<String, dynamic>>>(
          future: trackRepo.getPlaylists(),
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (!snapshot.hasData || snapshot.data!.isEmpty) {
              return const Center(child: Text('No playlists found'));
            }

            final playlists = snapshot.data!;
            return ListView.builder(
              itemCount: playlists.length,
              itemBuilder: (context, index) {
                final playlist = playlists[index];
                return ListTile(
                  leading: const Icon(Icons.playlist_play),
                  title: Text(playlist['name'] ?? 'Untitled'),
                  onTap: () async {
                    final success = await trackRepo.addToPlaylist(
                      playlist['id'].toString(),
                      track.id,
                    );
                    if (context.mounted) {
                      Navigator.pop(context);
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text(
                            success
                                ? 'Added to ${playlist['name']}'
                                : 'Failed to add to playlist',
                          ),
                        ),
                      );
                    }
                  },
                );
              },
            );
          },
        );
      },
    );
  }
}
