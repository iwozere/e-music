import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'theme/app_colors.dart';
import 'logic/blocs/audio_player_bloc.dart';
import 'logic/blocs/search_bloc.dart';
import 'repositories/api_client.dart';
import 'repositories/auth_repository.dart';
import 'repositories/track_repository.dart';
import 'ui/screens/login_screen.dart';

void main() {
  final apiClient = ApiClient(baseUrl: 'https://api.e-music.win');
  final authRepository = AuthRepository(apiClient: apiClient);
  final trackRepository = TrackRepository(apiClient: apiClient);

  runApp(
    MultiRepositoryProvider(
      providers: [
        RepositoryProvider.value(value: authRepository),
        RepositoryProvider.value(value: trackRepository),
      ],
      child: MultiBlocProvider(
        providers: [
          BlocProvider(
            create: (context) => AudioPlayerBloc(repository: trackRepository),
          ),
          BlocProvider(
            create: (context) => SearchBloc(trackRepository: trackRepository),
          ),
        ],
        child: const MySpotifyApp(),
      ),
    ),
  );
}

class MySpotifyApp extends StatelessWidget {
  const MySpotifyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MySpotify',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        primaryColor: AppColors.primary,
        scaffoldBackgroundColor: AppColors.background,
        cardColor: AppColors.surface,
        colorScheme: const ColorScheme.dark(
          primary: AppColors.primary,
          secondary: AppColors.primary,
          surface: AppColors.surface,
          surfaceContainer: AppColors.background,
        ),
        textTheme: const TextTheme(
          headlineMedium: TextStyle(
            color: AppColors.textMain,
            fontWeight: FontWeight.bold,
          ),
          bodyLarge: TextStyle(color: AppColors.textMuted),
        ),
      ),
      home: const LoginScreen(),
    );
  }
}
