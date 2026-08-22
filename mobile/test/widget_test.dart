// Smoke test: verifies LoginScreen renders without throwing.
//
// Pumping the full MySpotifyApp would also require AudioPlayerBloc/SearchBloc
// providers and a live AudioService platform-channel handler (main.dart sets
// these up before runApp() — MiniPlayer, part of MySpotifyApp's persistent
// chrome, needs AudioPlayerBloc even just to build LoginScreen's route), so
// this tests LoginScreen directly instead. LoginScreen itself only reaches
// into context.read<AuthRepository>() inside button callbacks, not during
// build, so no repository/provider setup is needed here either.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile/ui/screens/login_screen.dart';

void main() {
  testWidgets('LoginScreen renders', (WidgetTester tester) async {
    // Default test surface (800x600) is smaller than a real phone and
    // overflows this form; use a representative phone-sized viewport.
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const MaterialApp(home: LoginScreen()));

    expect(find.text('MySpotify'), findsOneWidget);
    expect(find.text('Your music, your space.'), findsOneWidget);
  });
}
