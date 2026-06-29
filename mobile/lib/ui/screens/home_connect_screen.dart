import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../models/user.dart';
import '../../repositories/auth_repository.dart';
import '../../services/discovery_service.dart';
import '../../theme/app_colors.dart';
import 'home_screen.dart';

/// "Home Remote" connect screen (docs/features-v7.md §6): find a MySpotify desktop on the
/// same Wi-Fi (mDNS) or enter its address manually, then pair with the PIN shown on the PC.
class HomeConnectScreen extends StatefulWidget {
  const HomeConnectScreen({super.key});

  @override
  State<HomeConnectScreen> createState() => _HomeConnectScreenState();
}

class _HomeConnectScreenState extends State<HomeConnectScreen> {
  final _hostController = TextEditingController();
  final _portController = TextEditingController(text: '8000');
  final _pinController = TextEditingController();

  bool _scanning = false;
  bool _connecting = false;
  List<DiscoveredServer> _found = [];

  @override
  void initState() {
    super.initState();
    _scan();
  }

  Future<void> _scan() async {
    setState(() => _scanning = true);
    final servers = await DiscoveryService().discover();
    if (!mounted) return;
    setState(() {
      _found = servers;
      _scanning = false;
    });
  }

  Future<void> _connect() async {
    final host = _hostController.text.trim();
    final port = int.tryParse(_portController.text.trim()) ?? 0;
    final pin = _pinController.text.trim();
    if (host.isEmpty || port == 0 || pin.isEmpty) {
      _toast('Enter the address, port, and PIN shown on your PC.');
      return;
    }
    setState(() => _connecting = true);
    final auth = context.read<AuthRepository>();
    final User? user = await auth.pairWithHomeServer(
      baseUrl: 'http://$host:$port/api/v1',
      pin: pin,
    );
    if (!mounted) return;
    setState(() => _connecting = false);
    if (user != null) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const HomeScreen()),
        (route) => false,
      );
    } else {
      _toast('Could not connect. Check the address and PIN, and that both devices are on the same Wi-Fi.');
    }
  }

  void _toast(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Connect to Home Server')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'On your PC, run MySpotify with Home Remote enabled. It shows an address and a PIN. '
            'Pick it below or type the address, then enter the PIN.',
            style: TextStyle(color: Colors.white70),
          ),
          const SizedBox(height: 20),

          // Discovered servers
          Row(
            children: [
              const Text('Found on your network',
                  style: TextStyle(fontWeight: FontWeight.bold)),
              const Spacer(),
              IconButton(
                onPressed: _scanning ? null : _scan,
                icon: _scanning
                    ? const SizedBox(
                        width: 18, height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.refresh),
              ),
            ],
          ),
          if (_found.isEmpty && !_scanning)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text('No servers found yet — enter the address below.',
                  style: TextStyle(color: Colors.white54)),
            ),
          ..._found.map(
            (s) => Card(
              color: AppColors.surface,
              child: ListTile(
                leading: const Icon(Icons.computer, color: AppColors.primary),
                title: Text(s.name),
                subtitle: Text('${s.host}:${s.port}'),
                onTap: () {
                  setState(() {
                    _hostController.text = s.host;
                    _portController.text = s.port.toString();
                  });
                },
              ),
            ),
          ),

          const SizedBox(height: 16),
          const Divider(color: Colors.white24),
          const SizedBox(height: 16),

          Row(
            children: [
              Expanded(
                flex: 3,
                child: TextField(
                  controller: _hostController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Address (e.g. 192.168.1.20)'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 1,
                child: TextField(
                  controller: _portController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Port'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _pinController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'Pairing PIN'),
          ),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _connecting ? null : _connect,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primary,
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
              child: _connecting
                  ? const SizedBox(
                      width: 20, height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Text('Connect', style: TextStyle(fontWeight: FontWeight.bold)),
            ),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _hostController.dispose();
    _portController.dispose();
    _pinController.dispose();
    super.dispose();
  }
}
