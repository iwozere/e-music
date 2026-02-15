import 'dart:convert';
import 'package:google_sign_in/google_sign_in.dart';
import '../models/user.dart';
import 'api_client.dart';

class AuthRepository {
  final ApiClient apiClient;
  final GoogleSignIn _googleSignIn = GoogleSignIn(
    scopes: ['email', 'openid', 'profile'],
    serverClientId:
        '342747071263-p0a752cdvvj39kuvfsnp2pabrqvb1ivs.apps.googleusercontent.com',
  );

  AuthRepository({required this.apiClient});

  Future<User?> register({
    required String username,
    required String email,
    required String password,
  }) async {
    try {
      final response = await apiClient.post(
        '/auth/register',
        body: {'username': username, 'email': email, 'password': password},
        authenticated: false,
      );

      if (response.statusCode == 200) {
        return User.fromJson(jsonDecode(response.body));
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  Future<User?> loginWithEmail({
    required String username,
    required String password,
  }) async {
    try {
      final response = await apiClient.post(
        '/auth/token',
        body: {'username': username, 'password': password},
        authenticated: false,
        useFormData: true,
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final token = data['access_token'];

        await apiClient.saveToken(token);
        return await getCurrentUser();
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  Future<User?> signIn() async {
    // Existing Google Sign-In logic...
    try {
      final GoogleSignInAccount? account = await _googleSignIn.signIn();
      if (account == null) return null;

      await account.authentication;
      final String? serverAuthCode = account.serverAuthCode;

      final response = await apiClient.get(
        '/auth/callback?code=$serverAuthCode',
        authenticated: false,
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final token = data['access_token'];
        final userData = data['user'];

        await apiClient.saveToken(token);
        return User.fromJson(userData);
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  Future<void> signOut() async {
    await _googleSignIn.signOut();
    await apiClient.deleteToken();
  }

  Future<User?> getCurrentUser() async {
    final token = await apiClient.getToken();
    if (token == null) return null;

    final response = await apiClient.get('/auth/me');
    if (response.statusCode == 200) {
      return User.fromJson(jsonDecode(response.body));
    }
    return null;
  }
}
