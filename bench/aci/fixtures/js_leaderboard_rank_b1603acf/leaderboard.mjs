/**
 * Ranks players by points (descending), breaking ties by name (ascending).
 *
 * @param {{ name: string, points: number }[]} players - Array of player objects.
 * @returns {string[]} Array of "name:points" strings in ranked order.
 */
export function rank_players(players) {
  return [...players]
    .sort((a, b) => {
      if (b.points !== a.points) {
        return b.points - a.points;
      }
      if (a.name < b.name) return 1;
      if (a.name > b.name) return -1;
      return 0;
    })
    .map((player) => `${player.name}:${player.points}`);
}
