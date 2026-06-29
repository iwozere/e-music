import 'package:multicast_dns/multicast_dns.dart';

/// A MySpotify desktop instance found on the LAN via mDNS ("Home Remote", Phase 7).
class DiscoveredServer {
  final String name;
  final String host;
  final int port;

  const DiscoveredServer({
    required this.name,
    required this.host,
    required this.port,
  });

  /// Base URL the mobile ApiClient expects (includes the /api/v1 suffix).
  String get apiBaseUrl => 'http://$host:$port/api/v1';
}

/// Browses for desktops advertising `_myspotify._tcp` (see backend app/desktop.py).
class DiscoveryService {
  static const String _serviceType = '_myspotify._tcp.local';

  /// Discover instances on the local network. Best-effort: returns whatever was found
  /// before [timeout]. Never throws — returns an empty list on any failure.
  Future<List<DiscoveredServer>> discover({
    Duration timeout = const Duration(seconds: 4),
  }) async {
    final results = <String, DiscoveredServer>{};
    final client = MDnsClient();
    try {
      await client.start();
      await for (final PtrResourceRecord ptr in client
          .lookup<PtrResourceRecord>(
            ResourceRecordQuery.serverPointer(_serviceType),
          )
          .timeout(timeout, onTimeout: (sink) => sink.close())) {
        await for (final SrvResourceRecord srv
            in client.lookup<SrvResourceRecord>(
          ResourceRecordQuery.service(ptr.domainName),
        )) {
          await for (final IPAddressResourceRecord ip
              in client.lookup<IPAddressResourceRecord>(
            ResourceRecordQuery.addressIPv4(srv.target),
          )) {
            final server = DiscoveredServer(
              name: ptr.domainName.split('.').first,
              host: ip.address.address,
              port: srv.port,
            );
            results['${server.host}:${server.port}'] = server;
          }
        }
      }
    } catch (_) {
      // mDNS unavailable / blocked — caller falls back to manual entry.
    } finally {
      client.stop();
    }
    return results.values.toList();
  }
}
