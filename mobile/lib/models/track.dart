class Track {
  final String id;
  final String title;
  final String? artist;
  final String? album;
  final String sourceType;
  final String? remoteId;
  final String? localPath;
  final bool isCached;
  final int? duration;
  final String? thumbnail;
  final bool isLiked;

  Track({
    required this.id,
    required this.title,
    this.artist,
    this.album,
    required this.sourceType,
    this.remoteId,
    this.localPath,
    this.isCached = false,
    this.duration,
    this.thumbnail,
    this.isLiked = false,
  });

  factory Track.fromJson(Map<String, dynamic> json) {
    return Track(
      id: json['id'] ?? '',
      title: json['title'] ?? 'Unknown',
      artist: json['artist'],
      album: json['album'],
      sourceType: json['source_type'] ?? 'local',
      remoteId: json['remote_id'],
      localPath: json['local_path'],
      isCached: json['is_cached'] ?? false,
      duration: json['duration'],
      thumbnail: json['thumbnail'],
      isLiked: json['is_liked'] ?? false,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'title': title,
      'artist': artist,
      'album': album,
      'source_type': sourceType,
      'remote_id': remoteId,
      'local_path': localPath,
      'is_cached': isCached,
      'duration': duration,
      'thumbnail': thumbnail,
      'is_liked': isLiked,
    };
  }

  Track copyWith({
    String? id,
    String? title,
    String? artist,
    String? album,
    String? sourceType,
    String? remoteId,
    String? localPath,
    bool? isCached,
    int? duration,
    String? thumbnail,
    bool? isLiked,
  }) {
    return Track(
      id: id ?? this.id,
      title: title ?? this.title,
      artist: artist ?? this.artist,
      album: album ?? this.album,
      sourceType: sourceType ?? this.sourceType,
      remoteId: remoteId ?? this.remoteId,
      localPath: localPath ?? this.localPath,
      isCached: isCached ?? this.isCached,
      duration: duration ?? this.duration,
      thumbnail: thumbnail ?? this.thumbnail,
      isLiked: isLiked ?? this.isLiked,
    );
  }
}
