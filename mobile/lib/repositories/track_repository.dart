import 'dart:convert';
import '../models/track.dart';
import 'api_client.dart';

class TrackRepository {
  final ApiClient apiClient;

  TrackRepository({required this.apiClient});

  Future<List<Track>> searchTracks(
    String query, {
    int offset = 0,
    int limit = 20,
  }) async {
    final response = await apiClient.get(
      '/search?q=$query&offset=$offset&limit=$limit',
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((json) => Track.fromJson(json)).toList();
    }
    return [];
  }

  String getStreamUrl(String trackId) {
    return '${apiClient.baseUrl}/stream/$trackId';
  }

  Future<void> likeTrack(String trackId, {bool isLiked = true}) async {
    await apiClient.post('/tracks/$trackId/like?is_liked=$isLiked');
  }

  Future<void> playTrack(String trackId) async {
    await apiClient.post('/tracks/$trackId/play');
  }

  Future<List<Track>> getLikedTracks() async {
    final response = await apiClient.get('/tracks/liked');
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((json) => Track.fromJson(json)).toList();
    }
    return [];
  }

  Future<List<Map<String, dynamic>>> getPlaylists() async {
    final response = await apiClient.get('/playlists');
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.cast<Map<String, dynamic>>();
    }
    return [];
  }

  Future<List<Track>> getPlaylistTracks(String playlistId) async {
    final response = await apiClient.get('/playlists/$playlistId/tracks');
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((json) => Track.fromJson(json)).toList();
    }
    return [];
  }

  Future<bool> addToPlaylist(String playlistId, String trackId) async {
    final response = await apiClient.post(
      '/playlists/$playlistId/tracks',
      body: {'track_id': trackId},
      useFormData: true,
    );
    return response.statusCode == 200;
  }

  Future<bool> createPlaylist(String name) async {
    final response = await apiClient.post(
      '/playlists',
      body: {'name': name},
      useFormData: true,
    );
    return response.statusCode == 200 || response.statusCode == 201;
  }

  Future<bool> removeFromPlaylist(String playlistId, String trackId) async {
    final response = await apiClient.delete(
      '/playlists/$playlistId/tracks/$trackId',
    );
    return response.statusCode == 200;
  }

  Future<Map<String, dynamic>> getStorageInfo() async {
    final response = await apiClient.get('/system/storage');
    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    return {};
  }
}
