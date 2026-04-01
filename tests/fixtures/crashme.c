#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char name[32];
    int health;
    int armor;
    float position[3];
} Player;

typedef struct {
    Player* players;
    int count;
    int capacity;
} GameState;

GameState* create_game(int capacity) {
    GameState* game = (GameState*)malloc(sizeof(GameState));
    game->players = (Player*)malloc(sizeof(Player) * capacity);
    game->count = 0;
    game->capacity = capacity;
    return game;
}

void add_player(GameState* game, const char* name, int health) {
    if (game->count >= game->capacity) {
        printf("Game full!\n");
        return;
    }
    Player* p = &game->players[game->count];
    strncpy(p->name, name, 31);
    p->name[31] = '\0';
    p->health = health;
    p->armor = 0;
    p->position[0] = 0.0f;
    p->position[1] = 0.0f;
    p->position[2] = 0.0f;
    game->count++;
}

// BUG: off-by-one — accesses players[count] instead of players[count-1]
Player* get_last_player(GameState* game) {
    return &game->players[game->count];  // should be count - 1
}

void damage_player(Player* p, int amount) {
    int effective = amount - p->armor;
    if (effective < 0) effective = 0;
    p->health -= effective;
    printf("%s took %d damage, health: %d\n", p->name, effective, p->health);
}

void apply_poison(GameState* game) {
    // BUG: uses NULL pointer when game has 0 players
    Player* last = get_last_player(game);
    damage_player(last, 5);  // reads garbage or crashes
}

int main(int argc, char** argv) {
    printf("=== Game starting ===\n");

    GameState* game = create_game(4);
    add_player(game, "Alice", 100);
    add_player(game, "Bob", 80);
    add_player(game, "Charlie", 120);

    printf("\nPlayers added: %d\n", game->count);

    // This will access the wrong player (off-by-one in get_last_player)
    Player* last = get_last_player(game);
    printf("Last player: %s (health: %d)\n", last->name, last->health);

    // Damage the "last" player (actually garbage data)
    damage_player(last, 30);

    // Now try poison on an empty game — will crash
    GameState* empty_game = create_game(4);
    printf("\nApplying poison to empty game...\n");
    apply_poison(empty_game);

    printf("=== Game done ===\n");

    free(game->players);
    free(game);
    free(empty_game->players);
    free(empty_game);
    return 0;
}
