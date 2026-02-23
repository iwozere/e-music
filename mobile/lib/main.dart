import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'theme/app_colors.dart';
import 'logic/blocs/audio_player_bloc.dart';
import 'logic/blocs/search_bloc.dart';
import 'repositories/api_client.dart';
import 'repositories/auth_repository.dart';
import 'repositories/track_repository.dart';
import 'ui/screens/login_screen.dart';
import 'ui/widgets/mini_player.dart';
import 'ui/screens/player_screen.dart';
import 'package:audio_service/audio_service.dart';
import 'logic/audio_handler.dart';

class NavigationService {
  static final currentRoute = ValueNotifier<String?>(null);
  static final mainTabIndex = ValueNotifier<int>(0);
}

class MyNavigatorObserver extends NavigatorObserver {
  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    if (route.settings.name != null) {
      NavigationService.currentRoute.value = route.settings.name;
    }
    super.didPush(route, previousRoute);
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    if (previousRoute?.settings.name != null) {
      NavigationService.currentRoute.value = previousRoute?.settings.name;
    } else {
      NavigationService.currentRoute.value = null;
    }
    super.didPop(route, previousRoute);
  }
}

final MyNavigatorObserver appRouteObserver = MyNavigatorObserver();

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final audioHandler = await AudioService.init(
    builder: () => MyAudioHandler(),
    config: const AudioServiceConfig(
      androidNotificationChannelId: 'com.myspotify.mobile.channel.audio',
      androidNotificationChannelName: 'Music Playback',
      androidStopForegroundOnPause: true,
    ),
  );

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
            create: (context) => AudioPlayerBloc(
              repository: trackRepository,
              audioHandler: audioHandler,
            ),
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

  static final GlobalKey<NavigatorState> navigatorKey =
      GlobalKey<NavigatorState>();

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MySpotify',
      navigatorKey: navigatorKey,
      debugShowCheckedModeBanner: false,
      navigatorObservers: [appRouteObserver],
      onGenerateRoute: (settings) {
        if (settings.name == '/player') {
          return MaterialPageRoute(
            settings: settings,
            builder: (_) => const PlayerScreen(),
          );
        }
        return null;
      },
      builder: (context, child) {
        return Overlay(
          initialEntries: [
            OverlayEntry(
              builder: (context) => Scaffold(
                body: child!,
                bottomNavigationBar: ValueListenableBuilder<String?>(
                  valueListenable: NavigationService.currentRoute,
                  builder: (context, route, _) {
                    // Hide both if on /player or if we are not on a main tab (optional)
                    final isPlayerOpen = route == '/player';
                    if (isPlayerOpen) return const SizedBox.shrink();

                    return SafeArea(
                      top: false,
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            decoration: BoxDecoration(
                              border: Border(
                                top: BorderSide(
                                  color: Colors.white.withValues(alpha: 0.15),
                                  width: 0.5,
                                ),
                              ),
                            ),
                            child: const MiniPlayer(),
                          ),
                          ValueListenableBuilder<int>(
                            valueListenable: NavigationService.mainTabIndex,
                            builder: (context, index, _) {
                              // Only show Nav Bar if we are on a route that 'belongs' to the main shell
                              // For now, if currentRoute is null, we assume we are on Home.
                              final isMainShell = route == null || route == '/';

                              if (!isMainShell) return const SizedBox.shrink();

                              return Container(
                                decoration: BoxDecoration(
                                  border: Border(
                                    top: BorderSide(
                                      color: Colors.white.withValues(
                                        alpha: 0.1,
                                      ),
                                      width: 0.5,
                                    ),
                                  ),
                                ),
                                child: BottomNavigationBar(
                                  currentIndex: index,
                                  onTap: (newIndex) {
                                    NavigationService.mainTabIndex.value =
                                        newIndex;
                                    // Pop sub-routes (like PlaylistDetail) so the user sees the new tab
                                    MySpotifyApp.navigatorKey.currentState
                                        ?.popUntil((route) => route.isFirst);
                                  },
                                  backgroundColor: AppColors.surface,
                                  selectedItemColor: AppColors.primary,
                                  unselectedItemColor: Colors.white70,
                                  type: BottomNavigationBarType.fixed,
                                  items: const [
                                    BottomNavigationBarItem(
                                      icon: Icon(Icons.search),
                                      label: 'Search',
                                    ),
                                    BottomNavigationBarItem(
                                      icon: Icon(Icons.library_music),
                                      label: 'Library',
                                    ),
                                    BottomNavigationBarItem(
                                      icon: Icon(Icons.favorite),
                                      label: 'Liked',
                                    ),
                                  ],
                                ),
                              );
                            },
                          ),
                        ],
                      ),
                    );
                  },
                ),
              ),
            ),
          ],
        );
      },
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
