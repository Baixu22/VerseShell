import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rank_players } from './leaderboard.mjs';

export function test_orders_distinct_points_descending() {
  const players = [
    { name: 'Alice', points: 50 },
    { name: 'Bob', points: 90 },
    { name: 'Carol', points: 70 },
    { name: 'Dave', points: 10 },
    { name: 'Eve', points: 30 },
    { name: 'Frank', points: 80 },
    { name: 'Grace', points: 20 },
    { name: 'Heidi', points: 60 },
    { name: 'Ivan', points: 40 },
    { name: 'Judy', points: 100 },
    { name: 'Mallory', points: 55 },
    { name: 'Niaj', points: 25 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'Judy:100', 'Bob:90', 'Frank:80', 'Carol:70', 'Heidi:60', 'Mallory:55',
    'Alice:50', 'Ivan:40', 'Eve:30', 'Niaj:25', 'Grace:20', 'Dave:10',
  ]);
}

export function test_breaks_ties_by_name_ascending() {
  const players = [
    { name: 'zoe', points: 20 },
    { name: 'adam', points: 20 },
    { name: 'mike', points: 10 },
    { name: 'beth', points: 30 },
    { name: 'carl', points: 20 },
    { name: 'dana', points: 10 },
    { name: 'earl', points: 30 },
    { name: 'fay', points: 10 },
    { name: 'gail', points: 30 },
    { name: 'hank', points: 20 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'beth:30', 'earl:30', 'gail:30', 'adam:20', 'carl:20', 'hank:20',
    'zoe:20', 'dana:10', 'fay:10', 'mike:10',
  ]);
}

export function test_handles_already_sorted_input() {
  const players = [
    { name: 'aaron', points: 110 },
    { name: 'bella', points: 100 },
    { name: 'cindy', points: 90 },
    { name: 'derek', points: 80 },
    { name: 'ellen', points: 70 },
    { name: 'frank', points: 60 },
    { name: 'gina', points: 50 },
    { name: 'harry', points: 40 },
    { name: 'irene', points: 30 },
    { name: 'jack', points: 20 },
    { name: 'kate', points: 10 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'aaron:110', 'bella:100', 'cindy:90', 'derek:80', 'ellen:70', 'frank:60',
    'gina:50', 'harry:40', 'irene:30', 'jack:20', 'kate:10',
  ]);
}

export function test_reverses_ascending_input() {
  const players = [
    { name: 'aa', points: 1 },
    { name: 'bb', points: 2 },
    { name: 'cc', points: 3 },
    { name: 'dd', points: 4 },
    { name: 'ee', points: 5 },
    { name: 'ff', points: 6 },
    { name: 'gg', points: 7 },
    { name: 'hh', points: 8 },
    { name: 'ii', points: 9 },
    { name: 'jj', points: 10 },
    { name: 'kk', points: 11 },
    { name: 'll', points: 12 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'll:12', 'kk:11', 'jj:10', 'ii:9', 'hh:8', 'gg:7',
    'ff:6', 'ee:5', 'dd:4', 'cc:3', 'bb:2', 'aa:1',
  ]);
}

export function test_orders_negative_and_zero_points() {
  const players = [
    { name: 'alpha', points: -5 },
    { name: 'bravo', points: -10 },
    { name: 'charlie', points: -1 },
    { name: 'delta', points: 5 },
    { name: 'echo', points: 10 },
    { name: 'foxtrot', points: 0 },
    { name: 'golf', points: 0 },
    { name: 'hotel', points: -20 },
    { name: 'india', points: 15 },
    { name: 'juliet', points: -3 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'india:15', 'echo:10', 'delta:5', 'foxtrot:0', 'golf:0', 'charlie:-1',
    'juliet:-3', 'alpha:-5', 'bravo:-10', 'hotel:-20',
  ]);
}

export function test_sorts_alphabetically_when_all_points_equal() {
  const players = [
    { name: 'oscar', points: 42 },
    { name: 'lima', points: 42 },
    { name: 'bravo', points: 42 },
    { name: 'tango', points: 42 },
    { name: 'alpha', points: 42 },
    { name: 'sierra', points: 42 },
    { name: 'golf', points: 42 },
    { name: 'delta', points: 42 },
    { name: 'romeo', points: 42 },
    { name: 'kilo', points: 42 },
    { name: 'yankee', points: 42 },
    { name: 'echo', points: 42 },
    { name: 'papa', points: 42 },
    { name: 'mike', points: 42 },
    { name: 'zulu', points: 42 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'alpha:42', 'bravo:42', 'delta:42', 'echo:42', 'golf:42', 'kilo:42',
    'lima:42', 'mike:42', 'oscar:42', 'papa:42', 'romeo:42', 'sierra:42',
    'tango:42', 'yankee:42', 'zulu:42',
  ]);
}

export function test_sorts_uppercase_before_lowercase_on_ties() {
  const players = [
    { name: 'bravo', points: 7 },
    { name: 'Alpha', points: 7 },
    { name: 'charlie', points: 7 },
    { name: 'Zulu', points: 7 },
    { name: 'delta', points: 7 },
    { name: 'Yankee', points: 7 },
    { name: 'echo', points: 7 },
    { name: 'Mike', points: 7 },
    { name: 'foxtrot', points: 7 },
    { name: 'Bravo', points: 7 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'Alpha:7', 'Bravo:7', 'Mike:7', 'Yankee:7', 'Zulu:7',
    'bravo:7', 'charlie:7', 'delta:7', 'echo:7', 'foxtrot:7',
  ]);
}

export function test_sorts_prefix_names_by_length_on_ties() {
  const players = [
    { name: 'Annette', points: 5 },
    { name: 'Annalise', points: 5 },
    { name: 'Anna', points: 5 },
    { name: 'Annie', points: 5 },
    { name: 'Ann', points: 5 },
    { name: 'Annika', points: 5 },
    { name: 'AnnaBell', points: 5 },
    { name: 'Annmarie', points: 5 },
    { name: 'AnnaMarie', points: 5 },
    { name: 'Annabelle', points: 5 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'Ann:5', 'Anna:5', 'AnnaBell:5', 'AnnaMarie:5', 'Annabelle:5',
    'Annalise:5', 'Annette:5', 'Annie:5', 'Annika:5', 'Annmarie:5',
  ]);
}

export function test_does_not_mutate_input_array() {
  const players = [
    { name: 'walter', points: 3 },
    { name: 'alice', points: 9 },
    { name: 'mona', points: 5 },
    { name: 'zed', points: 1 },
    { name: 'bob', points: 7 },
    { name: 'quinn', points: 2 },
    { name: 'xena', points: 8 },
    { name: 'carl', points: 6 },
    { name: 'nina', points: 4 },
    { name: 'yuri', points: 0 },
    { name: 'dan', points: 10 },
    { name: 'emma', points: 11 },
  ];
  const ranked = rank_players(players);
  assert.deepStrictEqual(ranked, [
    'emma:11', 'dan:10', 'alice:9', 'xena:8', 'bob:7', 'carl:6',
    'mona:5', 'nina:4', 'walter:3', 'quinn:2', 'zed:1', 'yuri:0',
  ]);
  assert.deepStrictEqual(players.map((p) => `${p.name}:${p.points}`), [
    'walter:3', 'alice:9', 'mona:5', 'zed:1', 'bob:7', 'quinn:2',
    'xena:8', 'carl:6', 'nina:4', 'yuri:0', 'dan:10', 'emma:11',
  ]);
}

export function test_compares_points_numerically_not_lexicographically() {
  const players = [
    { name: 'n9', points: 9 },
    { name: 'n10', points: 10 },
    { name: 'n100', points: 100 },
    { name: 'n1000', points: 1000 },
    { name: 'n2', points: 2 },
    { name: 'n20', points: 20 },
    { name: 'n200', points: 200 },
    { name: 'n3', points: 3 },
    { name: 'n33', points: 33 },
    { name: 'n333', points: 333 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'n1000:1000', 'n333:333', 'n200:200', 'n100:100', 'n33:33',
    'n20:20', 'n10:10', 'n9:9', 'n3:3', 'n2:2',
  ]);
}

export function test_handles_three_tiers_with_many_ties() {
  const players = [
    { name: 'charlie', points: 100 },
    { name: 'golf', points: 1 },
    { name: 'bravo', points: 50 },
    { name: 'alpha', points: 100 },
    { name: 'india', points: 1 },
    { name: 'delta', points: 50 },
    { name: 'echo', points: 100 },
    { name: 'mike', points: 1 },
    { name: 'foxtrot', points: 50 },
    { name: 'tango', points: 100 },
    { name: 'papa', points: 1 },
    { name: 'hotel', points: 50 },
    { name: 'oscar', points: 100 },
    { name: 'romeo', points: 1 },
    { name: 'juliet', points: 50 },
    { name: 'kilo', points: 100 },
    { name: 'yankee', points: 1 },
    { name: 'lima', points: 50 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'alpha:100', 'charlie:100', 'echo:100', 'kilo:100', 'oscar:100', 'tango:100',
    'bravo:50', 'delta:50', 'foxtrot:50', 'hotel:50', 'juliet:50', 'lima:50',
    'golf:1', 'india:1', 'mike:1', 'papa:1', 'romeo:1', 'yankee:1',
  ]);
}

export function test_formats_fractional_points() {
  const players = [
    { name: 'joe', points: 1.5 },
    { name: 'amy', points: 10.5 },
    { name: 'ivy', points: 2.5 },
    { name: 'ben', points: 9.25 },
    { name: 'hal', points: 3.75 },
    { name: 'cal', points: 8.75 },
    { name: 'gus', points: 4.25 },
    { name: 'dee', points: 7.5 },
    { name: 'fay', points: 5.5 },
    { name: 'eli', points: 6.5 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'amy:10.5', 'ben:9.25', 'cal:8.75', 'dee:7.5', 'eli:6.5',
    'fay:5.5', 'gus:4.25', 'hal:3.75', 'ivy:2.5', 'joe:1.5',
  ]);
}

export function test_breaks_ties_lexicographically_for_numbered_names() {
  const players = [
    { name: 'p10', points: 100 },
    { name: 'p2', points: 100 },
    { name: 'p1', points: 100 },
    { name: 'p30', points: 100 },
    { name: 'p3', points: 100 },
    { name: 'p20', points: 100 },
    { name: 'p5', points: 100 },
    { name: 'p40', points: 100 },
    { name: 'p4', points: 100 },
    { name: 'p50', points: 100 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'p1:100', 'p10:100', 'p2:100', 'p20:100', 'p3:100',
    'p30:100', 'p4:100', 'p40:100', 'p5:100', 'p50:100',
  ]);
}

export function test_ranks_twenty_players_with_distinct_points() {
  const players = [
    { name: 'v07', points: 14 },
    { name: 'v13', points: 8 },
    { name: 'v02', points: 19 },
    { name: 'v18', points: 3 },
    { name: 'v09', points: 12 },
    { name: 'v15', points: 6 },
    { name: 'v01', points: 20 },
    { name: 'v11', points: 10 },
    { name: 'v05', points: 16 },
    { name: 'v17', points: 4 },
    { name: 'v03', points: 18 },
    { name: 'v19', points: 2 },
    { name: 'v08', points: 13 },
    { name: 'v14', points: 7 },
    { name: 'v04', points: 17 },
    { name: 'v20', points: 1 },
    { name: 'v10', points: 11 },
    { name: 'v16', points: 5 },
    { name: 'v06', points: 15 },
    { name: 'v12', points: 9 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'v01:20', 'v02:19', 'v03:18', 'v04:17', 'v05:16', 'v06:15', 'v07:14',
    'v08:13', 'v09:12', 'v10:11', 'v11:10', 'v12:9', 'v13:8', 'v14:7',
    'v15:6', 'v16:5', 'v17:4', 'v18:3', 'v19:2', 'v20:1',
  ]);
}

export function test_keeps_duplicate_names_adjacent_on_ties() {
  const players = [
    { name: 'dup', points: 9 },
    { name: 'ant', points: 8 },
    { name: 'dup', points: 9 },
    { name: 'bee', points: 7 },
    { name: 'cat', points: 6 },
    { name: 'dup', points: 9 },
    { name: 'dog', points: 5 },
    { name: 'elk', points: 4 },
    { name: 'fox', points: 3 },
    { name: 'gut', points: 2 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'dup:9', 'dup:9', 'dup:9', 'ant:8', 'bee:7',
    'cat:6', 'dog:5', 'elk:4', 'fox:3', 'gut:2',
  ]);
}

export function test_sorts_punctuation_names_by_code_units() {
  const players = [
    { name: 'a~b', points: 3 },
    { name: 'a b', points: 3 },
    { name: 'a_b', points: 3 },
    { name: 'a!b', points: 3 },
    { name: 'aZb', points: 3 },
    { name: 'a-b', points: 3 },
    { name: 'aab', points: 3 },
    { name: 'a.b', points: 3 },
    { name: 'a0b', points: 3 },
    { name: 'aAb', points: 3 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'a b:3', 'a!b:3', 'a-b:3', 'a.b:3', 'a0b:3',
    'aAb:3', 'aZb:3', 'a_b:3', 'aab:3', 'a~b:3',
  ]);
}

export function test_puts_tied_leaders_in_name_order() {
  const players = [
    { name: 'zack', points: 95 },
    { name: 'bella', points: 80 },
    { name: 'mike', points: 95 },
    { name: 'chris', points: 75 },
    { name: 'adam', points: 95 },
    { name: 'dana', points: 70 },
    { name: 'elmo', points: 65 },
    { name: 'fiona', points: 60 },
    { name: 'greg', points: 55 },
    { name: 'hana', points: 50 },
    { name: 'ivan', points: 45 },
    { name: 'julia', points: 40 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'adam:95', 'mike:95', 'zack:95', 'bella:80', 'chris:75', 'dana:70',
    'elmo:65', 'fiona:60', 'greg:55', 'hana:50', 'ivan:45', 'julia:40',
  ]);
}

export function test_sorts_all_zero_point_players_alphabetically() {
  const players = [
    { name: 'nova', points: 0 },
    { name: 'liam', points: 0 },
    { name: 'mia', points: 0 },
    { name: 'noah', points: 0 },
    { name: 'emma', points: 0 },
    { name: 'olivia', points: 0 },
    { name: 'ethan', points: 0 },
    { name: 'ava', points: 0 },
    { name: 'lucas', points: 0 },
    { name: 'sophia', points: 0 },
    { name: 'mason', points: 0 },
    { name: 'isabella', points: 0 },
  ];
  assert.deepStrictEqual(rank_players(players), [
    'ava:0', 'emma:0', 'ethan:0', 'isabella:0', 'liam:0', 'lucas:0',
    'mason:0', 'mia:0', 'noah:0', 'nova:0', 'olivia:0', 'sophia:0',
  ]);
}

test('orders distinct players by descending points', test_orders_distinct_points_descending);
test('breaks ties by name ascending', test_breaks_ties_by_name_ascending);
test('handles already sorted input', test_handles_already_sorted_input);
test('reverses ascending input', test_reverses_ascending_input);
test('orders negative and zero points', test_orders_negative_and_zero_points);
test('sorts alphabetically when all points equal', test_sorts_alphabetically_when_all_points_equal);
test('sorts uppercase before lowercase on ties', test_sorts_uppercase_before_lowercase_on_ties);
test('sorts prefix names by length on ties', test_sorts_prefix_names_by_length_on_ties);
test('does not mutate input array', test_does_not_mutate_input_array);
test('compares points numerically not lexicographically', test_compares_points_numerically_not_lexicographically);
test('handles three tiers with many ties', test_handles_three_tiers_with_many_ties);
test('formats fractional points', test_formats_fractional_points);
test('breaks ties lexicographically for numbered names', test_breaks_ties_lexicographically_for_numbered_names);
test('ranks twenty players with distinct points', test_ranks_twenty_players_with_distinct_points);
test('keeps duplicate names adjacent on ties', test_keeps_duplicate_names_adjacent_on_ties);
test('sorts punctuation names by code units', test_sorts_punctuation_names_by_code_units);
test('puts tied leaders in name order', test_puts_tied_leaders_in_name_order);
test('sorts all zero point players alphabetically', test_sorts_all_zero_point_players_alphabetically);
