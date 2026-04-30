import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

class DownloadService {
  /// Downloads a track audio file to internal app storage.
  /// Uses internal app documents dir — no special Android permissions needed.
  /// Returns the local file path on success, null on failure.
  static Future<String?> downloadTrack({
    required String trackId,
    required String streamUrl,
  }) async {
    try {
      final dir = await getApplicationDocumentsDirectory();
      final tracksDir = Directory('${dir.path}/tracks');
      await tracksDir.create(recursive: true);
      final filePath = '${tracksDir.path}/$trackId.mp3';

      if (File(filePath).existsSync()) return filePath;

      final request = http.Request('GET', Uri.parse(streamUrl));
      final streamResponse = await http.Client().send(request);

      if (streamResponse.statusCode != 200) {
        _log('Download HTTP ${streamResponse.statusCode} for $trackId');
        return null;
      }

      final file = File(filePath);
      final sink = file.openWrite();
      await streamResponse.stream.pipe(sink);
      await sink.close();

      _log('Downloaded $trackId → $filePath');
      return filePath;
    } catch (e) {
      _log('Download failed for $trackId: $e');
      return null;
    }
  }

  /// Returns the local path if a track has already been downloaded, else null.
  static Future<String?> localPath(String trackId) async {
    final dir = await getApplicationDocumentsDirectory();
    final path = '${dir.path}/tracks/$trackId.mp3';
    return File(path).existsSync() ? path : null;
  }

  static void _log(String msg) {
    // ignore: avoid_print
    print('MYSPOTIFY_DOWNLOAD: $msg');
  }
}
