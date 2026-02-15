import 'package:flutter_bloc/flutter_bloc.dart';
import '../../models/track.dart';
import '../../repositories/track_repository.dart';

abstract class SearchEvent {}

class SearchQueryChanged extends SearchEvent {
  final String query;
  SearchQueryChanged(this.query);
}

class LoadMoreSearch extends SearchEvent {}

abstract class SearchState {}

class SearchInitial extends SearchState {}

class SearchLoading extends SearchState {}

class SearchSuccess extends SearchState {
  final List<Track> tracks;
  final String query;
  final bool hasMore;
  final bool isFetchingMore;

  SearchSuccess({
    required this.tracks,
    required this.query,
    this.hasMore = true,
    this.isFetchingMore = false,
  });

  SearchSuccess copyWith({
    List<Track>? tracks,
    String? query,
    bool? hasMore,
    bool? isFetchingMore,
  }) {
    return SearchSuccess(
      tracks: tracks ?? this.tracks,
      query: query ?? this.query,
      hasMore: hasMore ?? this.hasMore,
      isFetchingMore: isFetchingMore ?? this.isFetchingMore,
    );
  }
}

class SearchFailure extends SearchState {
  final String error;
  SearchFailure(this.error);
}

class SearchBloc extends Bloc<SearchEvent, SearchState> {
  final TrackRepository trackRepository;
  static const int _limit = 20;

  SearchBloc({required this.trackRepository}) : super(SearchInitial()) {
    on<SearchQueryChanged>((event, emit) async {
      if (event.query.isEmpty) {
        emit(SearchInitial());
        return;
      }

      emit(SearchLoading());
      try {
        final tracks = await trackRepository.searchTracks(
          event.query,
          limit: _limit,
        );
        emit(
          SearchSuccess(
            tracks: tracks,
            query: event.query,
            hasMore: tracks.length >= _limit,
          ),
        );
      } catch (e) {
        emit(SearchFailure(e.toString()));
      }
    });

    on<LoadMoreSearch>((event, emit) async {
      final currentState = state;
      if (currentState is SearchSuccess &&
          currentState.hasMore &&
          !currentState.isFetchingMore) {
        emit(currentState.copyWith(isFetchingMore: true));
        try {
          final tracks = await trackRepository.searchTracks(
            currentState.query,
            offset: currentState.tracks.length,
            limit: _limit,
          );
          emit(
            currentState.copyWith(
              tracks: [...currentState.tracks, ...tracks],
              hasMore: tracks.length >= _limit,
              isFetchingMore: false,
            ),
          );
        } catch (e) {
          emit(currentState.copyWith(isFetchingMore: false));
        }
      }
    });
  }
}
