import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class ApiClient {
  final String baseUrl;
  final _storage = const FlutterSecureStorage();

  static const _kAccess = 'jwt_token';
  static const _kRefresh = 'jwt_refresh_token';

  ApiClient({required this.baseUrl});

  Future<String?> getToken() async {
    return await _storage.read(key: _kAccess);
  }

  Future<String?> getRefreshToken() async {
    return await _storage.read(key: _kRefresh);
  }

  Future<void> saveToken(String token) async {
    await _storage.write(key: _kAccess, value: token);
  }

  Future<void> saveRefreshToken(String token) async {
    await _storage.write(key: _kRefresh, value: token);
  }

  Future<void> saveTokenPair(String access, String refresh) async {
    await saveToken(access);
    await saveRefreshToken(refresh);
  }

  Future<void> deleteToken() async {
    await _storage.delete(key: _kAccess);
    await _storage.delete(key: _kRefresh);
  }

  Future<bool> _tryRefresh() async {
    final refresh = await getRefreshToken();
    if (refresh == null || refresh.isEmpty) return false;
    final response = await http.post(
      Uri.parse('$baseUrl/auth/refresh'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'refresh_token': refresh}),
    );
    if (response.statusCode != 200) return false;
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final access = data['access_token'] as String?;
    final next = data['refresh_token'] as String?;
    if (access == null || next == null) return false;
    await saveTokenPair(access, next);
    return true;
  }

  Future<http.Response> get(
    String endpoint, {
    bool authenticated = true,
    bool retryOn401 = true,
  }) async {
    Map<String, String> headers = {'Content-Type': 'application/json'};

    if (authenticated) {
      String? token = await getToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
    }

    http.Response response = await http.get(
      Uri.parse('$baseUrl$endpoint'),
      headers: headers,
    );
    if (authenticated &&
        retryOn401 &&
        response.statusCode == 401 &&
        await _tryRefresh()) {
      String? token = await getToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
      response = await http.get(Uri.parse('$baseUrl$endpoint'), headers: headers);
    }
    return response;
  }

  Future<http.Response> post(
    String endpoint, {
    Map<String, dynamic>? body,
    bool authenticated = true,
    bool useFormData = false,
    bool retryOn401 = true,
  }) async {
    Map<String, String> headers = {};
    if (!useFormData) {
      headers['Content-Type'] = 'application/json';
    } else {
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
    }

    if (authenticated) {
      String? token = await getToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
    }

    dynamic finalBody;
    if (useFormData && body != null) {
      finalBody = body.map((key, value) => MapEntry(key, value.toString()));
    } else {
      finalBody = body != null ? jsonEncode(body) : null;
    }

    http.Response response = await http.post(
      Uri.parse('$baseUrl$endpoint'),
      headers: headers,
      body: finalBody,
    );
    if (authenticated &&
        retryOn401 &&
        response.statusCode == 401 &&
        _allowRefreshRetry(endpoint) &&
        await _tryRefresh()) {
      String? token = await getToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
      response = await http.post(
        Uri.parse('$baseUrl$endpoint'),
        headers: headers,
        body: finalBody,
      );
    }
    return response;
  }

  Future<http.Response> postMultipart(
    String endpoint, {
    required String fileField,
    required Uint8List fileBytes,
    required String filename,
    required String mimeType,
    bool authenticated = true,
    bool retryOn401 = true,
  }) async {
    Future<http.Response> send(String? token) async {
      final uri = Uri.parse('$baseUrl$endpoint');
      final request = http.MultipartRequest('POST', uri);
      if (token != null) request.headers['Authorization'] = 'Bearer $token';
      request.files.add(http.MultipartFile.fromBytes(
        fileField,
        fileBytes,
        filename: filename,
        contentType: MediaType.parse(mimeType),
      ));
      return http.Response.fromStream(await request.send());
    }

    final token = authenticated ? await getToken() : null;
    final response = await send(token);

    if (authenticated &&
        retryOn401 &&
        response.statusCode == 401 &&
        _allowRefreshRetry(endpoint) &&
        await _tryRefresh()) {
      return send(await getToken());
    }
    return response;
  }

  /// Avoid refresh loop on auth endpoints.
  static bool _allowRefreshRetry(String endpoint) {
    return !endpoint.startsWith('/auth/token') &&
        !endpoint.startsWith('/auth/refresh') &&
        !endpoint.startsWith('/auth/register');
  }

  Future<http.Response> delete(
    String endpoint, {
    bool authenticated = true,
    bool retryOn401 = true,
  }) async {
    Map<String, String> headers = {'Content-Type': 'application/json'};

    if (authenticated) {
      String? token = await getToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
    }

    http.Response response = await http.delete(
      Uri.parse('$baseUrl$endpoint'),
      headers: headers,
    );
    if (authenticated &&
        retryOn401 &&
        response.statusCode == 401 &&
        await _tryRefresh()) {
      String? token = await getToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
      response = await http.delete(
        Uri.parse('$baseUrl$endpoint'),
        headers: headers,
      );
    }
    return response;
  }
}
