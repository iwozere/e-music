import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:share_plus/share_plus.dart';
import '../../models/track.dart';
import '../../repositories/track_repository.dart';
import '../../logic/blocs/audio_player_bloc.dart';

class TrackListTile extends StatelessWidget {
  final Track track;
  final String? playlistId;
  final VoidCallback? onRemove;
  final VoidCallback? onLikeToggle;

  const TrackListTile({
    super.key,
    required this.track,
    this.playlistId,
    this.onRemove,
    this.onLikeToggle,
  });

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
              onLikeToggle?.call();
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(
                      track.isLiked ? 'Removed from Likes' : 'Added to Likes',
                    ),
                  ),
                );
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
            case 'remove':
              if (playlistId != null && onRemove != null) {
                final success = await trackRepo.removeFromPlaylist(
                  playlistId!,
                  track.id,
                );
                if (success) {
                  onRemove!();
                }
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(
                        success
                            ? 'Removed from playlist'
                            : 'Failed to remove from playlist',
                      ),
                    ),
                  );
                }
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
          if (playlistId != null)
            const PopupMenuItem(
              value: 'remove',
              child: Row(
                children: [
                  Icon(Icons.playlist_remove, color: Colors.red),
                  SizedBox(width: 8),
                  Text(
                    'Remove from Playlist',
                    style: TextStyle(color: Colors.red),
                  ),
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
