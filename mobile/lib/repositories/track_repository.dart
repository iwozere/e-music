import 'dart:convert';
import 'dart:typed_data';
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
      '/tracks/search?q=${Uri.encodeQueryComponent(query)}&offset=$offset&limit=$limit',
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((json) => Track.fromJson(json)).toList();
    }
    return [];
  }

  /// Signed stream URL from POST /tracks/stream/grant (short-lived).
  Future<String> getStreamUrl(String trackId) async {
    final response = await apiClient.post(
      '/tracks/stream/grant',
      body: {'track_id': trackId},
    );
    if (response.statusCode != 200) {
      throw Exception('stream grant failed: HTTP ${response.statusCode}');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final url = data['stream_url'] as String?;
    if (url == null || url.isEmpty) {
      throw Exception('missing stream_url in grant response');
    }
    return url;
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

  Future<bool> deletePlaylist(String playlistId) async {
    final response = await apiClient.delete('/playlists/$playlistId');
    return response.statusCode == 200;
  }

  Future<Map<String, dynamic>> getStorageInfo() async {
    final response = await apiClient.get('/system/storage');
    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    return {};
  }

  /// Queues a server-side permanent library import for a YouTube track.
  Future<bool> saveToLibrary(String trackId) async {
    final response = await apiClient.post('/tracks/$trackId/save-to-library');
    return response.statusCode == 200;
  }

  /// Sends recorded audio to the backend for Gemini melody identification.
  /// Returns {artist, title, confidence, remote_id, thumbnail} on success.
  /// Throws an [Exception] with a user-readable message on failure.
  Future<Map<String, dynamic>> identifyMelody(Uint8List audioBytes) async {
    final response = await apiClient.postMultipart(
      '/ai/identify',
      fileField: 'audio',
      fileBytes: audioBytes,
      filename: 'hum.m4a',
      mimeType: 'audio/mp4',
    );

    final body = jsonDecode(response.body) as Map<String, dynamic>;

    if (response.statusCode == 200) return body;

    // error_handlers.py shape: {message, detail}
    final detail = body['detail'];
    final msg = (detail is Map ? detail['message'] : null) ??
        body['message'] ??
        'Could not identify the melody';
    throw Exception(msg as String);
  }

  /// Fetches AI-suggested tracks from Groq based on the provided context track IDs.
  Future<List<Track>> getAiShuffle(List<String> trackIds) async {
    final response = await apiClient.post(
      '/tracks/ai-shuffle',
      body: {'track_ids': trackIds},
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((json) => Track.fromJson(json)).toList();
    }
    throw Exception('AI shuffle failed: HTTP ${response.statusCode}');
  }
}
