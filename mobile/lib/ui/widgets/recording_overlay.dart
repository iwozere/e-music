import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../../repositories/track_repository.dart';

enum _Phase { recording, identifying }

class RecordingOverlay extends StatefulWidget {
  final TrackRepository repository;
  final void Function(Map<String, dynamic> result) onSuccess;
  final void Function(String message) onError;

  const RecordingOverlay({
    super.key,
    required this.repository,
    required this.onSuccess,
    required this.onError,
  });

  @override
  State<RecordingOverlay> createState() => _RecordingOverlayState();
}

class _RecordingOverlayState extends State<RecordingOverlay> {
  static const _duration = 10;

  final _recorder = AudioRecorder();
  _Phase _phase = _Phase.recording;
  int _countdown = _duration;
  Timer? _ticker;
  bool _cancelled = false;
  String? _filePath;

  @override
  void initState() {
    super.initState();
    _startRecording();
  }

  Future<void> _startRecording() async {
    final hasPermission = await _recorder.hasPermission();
    if (!hasPermission) {
      if (mounted) Navigator.of(context).pop();
      widget.onError('Microphone permission denied');
      return;
    }

    final dir = await getTemporaryDirectory();
    _filePath = '${dir.path}/hum_${DateTime.now().millisecondsSinceEpoch}.m4a';

    await _recorder.start(
      const RecordConfig(
        encoder: AudioEncoder.aacLc,
        bitRate: 128000,
        sampleRate: 44100,
        numChannels: 1,
      ),
      path: _filePath!,
    );

    _ticker = Timer.periodic(const Duration(seconds: 1), (_) async {
      if (!mounted) return;
      setState(() => _countdown--);
      if (_countdown <= 0) {
        _ticker?.cancel();
        await _stopAndIdentify();
      }
    });
  }

  Future<void> _stopAndIdentify() async {
    final path = await _recorder.stop();
    if (_cancelled || !mounted) return;

    setState(() => _phase = _Phase.identifying);

    try {
      Uint8List bytes;
      if (path != null) {
        final file = File(path);
        bytes = await file.readAsBytes();
        await file.delete();
      } else {
        throw Exception('Recording failed — no audio captured');
      }

      final result = await widget.repository.identifyMelody(bytes);
      if (!mounted) return;
      Navigator.of(context).pop();
      widget.onSuccess(result);
    } catch (e) {
      if (!mounted) return;
      Navigator.of(context).pop();
      widget.onError(e.toString().replaceFirst('Exception: ', ''));
    }
  }

  void _cancel() {
    _cancelled = true;
    _ticker?.cancel();
    _recorder.stop();
    Navigator.of(context).pop();
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _recorder.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: const Color(0xFF1E293B),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 40),
        child: _phase == _Phase.recording
            ? _RecordingContent(countdown: _countdown, onCancel: _cancel)
            : const _IdentifyingContent(),
      ),
    );
  }
}

// ─── Recording state ──────────────────────────────────────────────────────────

class _RecordingContent extends StatelessWidget {
  final int countdown;
  final VoidCallback onCancel;

  const _RecordingContent({required this.countdown, required this.onCancel});

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const _WaveBars(),
        const SizedBox(height: 20),
        Text(
          '$countdown',
          style: const TextStyle(
            fontSize: 52,
            fontWeight: FontWeight.w800,
            color: Color(0xFF8B5CF6),
            height: 1,
          ),
        ),
        const SizedBox(height: 10),
        Text(
          'Hum or sing the melody…',
          style: TextStyle(
            color: Colors.white.withValues(alpha: 0.6),
            fontSize: 15,
          ),
        ),
        const SizedBox(height: 28),
        OutlinedButton(
          onPressed: onCancel,
          style: OutlinedButton.styleFrom(
            foregroundColor: Colors.white54,
            side: const BorderSide(color: Colors.white24),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 10),
          ),
          child: const Text('Cancel'),
        ),
      ],
    );
  }
}

// ─── Identifying state ────────────────────────────────────────────────────────

class _IdentifyingContent extends StatelessWidget {
  const _IdentifyingContent();

  @override
  Widget build(BuildContext context) {
    return const Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(height: 4),
        CircularProgressIndicator(color: Color(0xFF8B5CF6), strokeWidth: 3),
        SizedBox(height: 28),
        Text(
          'Identifying melody…',
          style: TextStyle(color: Colors.white70, fontSize: 15),
        ),
        SizedBox(height: 4),
      ],
    );
  }
}

// ─── Animated wave bars ───────────────────────────────────────────────────────

class _WaveBars extends StatefulWidget {
  const _WaveBars();

  @override
  State<_WaveBars> createState() => _WaveBarsState();
}

class _WaveBarsState extends State<_WaveBars>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  static const _maxHeights = [24.0, 44.0, 60.0, 44.0, 24.0];
  static const _phases = [0.00, 0.15, 0.30, 0.45, 0.60];

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 64,
      child: AnimatedBuilder(
        animation: _ctrl,
        builder: (_, _) {
          return Row(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: List.generate(5, (i) {
              final phase = (_ctrl.value + _phases[i]) % 1.0;
              final scale = (sin(phase * 2 * pi) + 1) / 2; // 0..1 smooth
              final h = 16.0 + (_maxHeights[i] - 16.0) * scale;
              return Container(
                width: 7,
                height: h,
                margin: const EdgeInsets.symmetric(horizontal: 3),
                decoration: BoxDecoration(
                  color: const Color(
                    0xFF8B5CF6,
                  ).withValues(alpha: 0.5 + 0.5 * scale),
                  borderRadius: BorderRadius.circular(4),
                ),
              );
            }),
          );
        },
      ),
    );
  }
}
