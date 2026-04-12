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
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final token = data['access_token'] as String?;
        final refresh = data['refresh_token'] as String?;
        if (token != null && refresh != null) {
          await apiClient.saveTokenPair(token, refresh);
        } else if (token != null) {
          await apiClient.saveToken(token);
        }
        return await getCurrentUser();
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  Future<User?> signIn() async {
    try {
      final GoogleSignInAccount? account = await _googleSignIn.signIn();
      if (account == null) return null;

      final GoogleSignInAuthentication auth = await account.authentication;
      final String? idToken = auth.idToken;
      if (idToken == null || idToken.isEmpty) return null;

      // Backend verifies ID tokens (same flow as web GSI). Do not use
      // /auth/callback here: server auth codes from the mobile SDK use a
      // different redirect than GOOGLE_REDIRECT_URI, so token exchange fails.
      final response = await apiClient.post(
        '/auth/google',
        body: {'id_token': idToken},
        authenticated: false,
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final token = data['access_token'] as String?;
        final refresh = data['refresh_token'] as String?;
        final userData = data['user'];

        if (token != null && refresh != null) {
          await apiClient.saveTokenPair(token, refresh);
        } else if (token != null) {
          await apiClient.saveToken(token);
        }
        return User.fromJson(userData as Map<String, dynamic>);
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  Future<void> signOut() async {
    final refresh = await apiClient.getRefreshToken();
    await _googleSignIn.signOut();
    if (refresh != null && refresh.isNotEmpty) {
      try {
        await apiClient.post(
          '/auth/logout',
          body: {'refresh_token': refresh},
          authenticated: false,
          retryOn401: false,
        );
      } catch (_) {}
    }
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
