"""Prepare the exact >=2000 Chess.com v2 puzzle snapshot for Maia3."""
import gzip
import hashlib
import json
import random
import urllib.request
import zipfile
from pathlib import Path

import chess
import ijson

ARCHIVE_URL = "https://github.com/IchNukeDichWeg/chess.com-puzzles/releases/download/v2/puzzles-json.zip"
ARCHIVE_SHA256 = "e1723a55970e9dbf36b3a2981183b571b979efe5ee7a83a500f7526813d7f406"
ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?{~}(^)[_]@#$"
SOURCE = Path("puzzles-json.zip")
DEST = Path("puzzles_2000plus.jsonl.gz")


def decode_tcn(start_fen, encoded):
    board = chess.Board(start_fen)
    result = []
    assert len(encoded) % 2 == 0
    for i in range(0, len(encoded), 2):
        a, b = ALPHABET.index(encoded[i]), ALPHABET.index(encoded[i + 1])
        promo = ""
        if b > 63:
            promo = "qnrbk"[(b - 64) // 3]
            b = a + (-8 if a < 16 else 8) + (b - 64) % 3 - 1
        uci = chess.square_name(a) + chess.square_name(b) + promo
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"Illegal source move {uci}: {start_fen}")
        result.append(uci)
        board.push(move)
    return result


def main():
    if not SOURCE.exists():
        with urllib.request.urlopen(ARCHIVE_URL, timeout=180) as response, SOURCE.open("wb") as f:
            while chunk := response.read(2 ** 20):
                f.write(chunk)
    digest = hashlib.file_digest(SOURCE.open("rb"), "sha256").hexdigest()
    if digest != ARCHIVE_SHA256:
        raise RuntimeError(f"Source archive hash mismatch: {digest}")
    rows = []
    with zipfile.ZipFile(SOURCE) as z, z.open("puzzles.json") as stream:
        for key, original in ijson.kvitems(stream, ""):
            rating = int(original["rating"])
            if rating < 2000:
                continue
            moves = decode_tcn(original["initialFen"], original["tcnMoveList"])
            assert len(moves) >= 2
            color = original["colorOfUser"].lower()
            b = chess.Board(original["initialFen"])
            b.push_uci(moves[0])
            assert ("white" if b.turn else "black") == color
            rows.append({"id": int(key), "rating": rating,
                         "initialFen": original["initialFen"],
                         "setupMoveUci": moves[0],
                         "solutionUci": moves[1:], "colorOfUser": color})
    rows.sort(key=lambda x: x["id"])
    random.Random(9509890422764783073).shuffle(rows)
    assert len({r["id"] for r in rows}) == len(rows)
    with gzip.open(DEST, "wt", encoding="utf-8", compresslevel=6) as output:
        for row in rows:
            output.write(json.dumps(row, separators=(",", ":")) + "\n")
    meta = {"source_sha256": digest, "total": len(rows), "cutoff": 2000,
            "shuffle_seed": "9509890422764783073",
            "dataset_sha256": hashlib.file_digest(DEST.open("rb"), "sha256").hexdigest(),
            "rating_min": min(r["rating"] for r in rows),
            "rating_max": max(r["rating"] for r in rows)}
    Path("dataset_info.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("PREPARED", json.dumps(meta), flush=True)


if __name__ == "__main__":
    main()
