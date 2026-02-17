import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class ApiClient {
  final String baseUrl;
  final _storage = const FlutterSecureStorage();

  ApiClient({required this.baseUrl});

  Future<String?> getToken() async {
    return await _storage.read(key: 'jwt_token');
  }

  Future<void> saveToken(String token) async {
    await _storage.write(key: 'jwt_token', value: token);
  }

  Future<void> deleteToken() async {
    await _storage.delete(key: 'jwt_token');
  }

  Future<http.Response> get(
    String endpoint, {
    bool authenticated = true,
  }) async {
    Map<String, String> headers = {'Content-Type': 'application/json'};

    if (authenticated) {
      String? token = await getToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
    }

    return await http.get(Uri.parse('$baseUrl$endpoint'), headers: headers);
  }

  Future<http.Response> post(
    String endpoint, {
    Map<String, dynamic>? body,
    bool authenticated = true,
    bool useFormData = false,
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

    return await http.post(
      Uri.parse('$baseUrl$endpoint'),
      headers: headers,
      body: finalBody,
    );
  }

  Future<http.Response> delete(
    String endpoint, {
    bool authenticated = true,
  }) async {
    Map<String, String> headers = {'Content-Type': 'application/json'};

    if (authenticated) {
      String? token = await getToken();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
    }

    return await http.delete(Uri.parse('$baseUrl$endpoint'), headers: headers);
  }
}
