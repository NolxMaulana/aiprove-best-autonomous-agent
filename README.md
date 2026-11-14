# best-autonomous-agent — AIProve entry

Entry untuk bounty **best-autonomous-agent** (0.3 GLD, AutoGrade, tutup
Minggu 15 Nov 2026 20:49 WIB): agent yang fully autonomous, tanpa human in
the loop. Ia membaca `aiprove.fun/skill.md`, sign in dengan keypair-nya
sendiri, lalu enter dan menyelesaikan bounty open sebanyak mungkin sendiri.

## Cara kerja agent

`agent.py` (Python 3.11+, satu-satunya dependency `pycryptodome` untuk
Keccak-256; matematika secp256k1 murni Python di dalam file) menjalankan loop:

1. **Fetch skill.md** — `GET https://aiprove.fun/skill.md`, verifikasi endpoint
   `auth/challenge`, `auth/verify`, `bounties`, `enter`, `submit` ada.
2. **Generate keypair baru** — secp256k1 ephemeral, dibuat fresh tiap run di
   memori (`secrets.randbits`). TIDAK PERNAH dibaca dari env/file/argumen,
   tidak pernah ditulis ke disk, tidak pernah ditampilkan. Identitas = address
   turunannya; log hanya menyimpan fingerprint SHA-256 address.
3. **Self-test signing lokal** — test vector (privkey 1, pubkey = generator G)
   plus EIP-191 `personal_sign` sign + recover round-trip, harus cocok.
4. **Auth (LIVE ONLY)** — `GET /api/auth/challenge`, sign challenge EIP-191,
   `POST /api/auth/verify` tukar session token (disimpan di memori saja,
   tidak pernah di-log isinya).
5. **List bounty open** — `GET /api/health`, `GET /api/bounties?status=open`,
   lalu detail tiap bounty (`GET /api/bounties/<slug>`, read-only).
6. **Klasifikasi tiap bounty** — `solvable` (ada solver lokal),
   `eligible-live` (loop-nya sendiri), atau `skipped` + alasan
   (hold-to-play, butuh posting X, butuh referral, PosterJudge subjektif,
   butuh data live yang tidak bisa diverifikasi, atau belum ada solver).
7. **Bangun entry secara lokal** (`solvers.py`) — forecast payload dari data
   harga publik, atau solusi kode + dites lokal (node/gcc). Tidak ada yang
   dikirim ke mana pun di langkah ini.
8. **Submit (LIVE ONLY)** — `POST enter` lalu `POST submit` per entry.
   Forecast submit prediction; code/loop submit `repoUrl` + `commit` +
   transcript.
9. **Laporan** — `out/report.json` berisi semua verdict dan langkah,
   tanpa secret apa pun.

## File

| File | Isi |
|---|---|
| `agent.py` | Loop autonomous utama (fetch, keypair, auth, klasifikasi, submit live) |
| `solvers.py` | Solver lokal: 2 forecast + 2 code, masing-masing terverifikasi |
| `requirements.txt` | `pycryptodome` (hanya untuk Keccak-256) |
| `README.md` | File ini |
| `TRANSCRIPT.md` | Transcript lengkap loop dry-run yang dijalankan |
| `out/report.json` | Laporan mesin dari run dry-run terakhir (32 langkah) |
| `out/forecast-btc-7d.payload.json` | Payload prediksi BTC (dry-run, belum disubmit) |
| `out/forecast-nvda-3d.payload.json` | Payload prediksi NVDA (dry-run, belum disubmit) |
| `out/solutions/code-golf-expr/solution.js` + `test.js` | `evalExpr`, dites node: 12/12 lolos |
| `out/solutions/fastest-primes/primes.c` (+ binary `primes`) | Sieve Eratosthenes, dites gcc: 5/5 lolos |

## Hasil uji lokal (dry-run, terverifikasi)

Run kanonis: Sabtu 14 Nov 2026, 22:20:17–22:20:46 WIB, exit 0.

- Bounty open dievaluasi: **20** (semua yang terdaftar saat itu)
- Solvable dan berhasil dibangun lokal: **4**
  - `forecast-btc-7d` — jawaban `no`, confidence 0.75 (CoinGecko BTC 7d:
    75.776,38 -> 65.505,30 USD, return -13,55%, momentum rule, confidence
    dibatasi maks 0,75)
  - `forecast-nvda-3d` — prediksi close 162,85 (Yahoo Finance, harga reguler
    terakhir 13 Nov 2026; baseline naive no-change)
  - `code-golf-expr` — `solution.js`, node test **12/12 PASS**
  - `fastest-primes` — `primes.c` (gcc -O2), **5/5 PASS**
    (pi(10)=4, pi(100)=25, pi(1000)=168, pi(100000)=9592, pi(5000000)=348513)
- Eligible-live (loop-nya sendiri, hanya bisa disubmit live): **2**
  (`sample-agent-skillmd`, `best-autonomous-agent`)
- Skipped dengan alasan tercatat: **14** — 5 hold-to-play (butuh hold $PROVE:
  `bughunt-stakepool`, `nvda-jensen-earnings`, `prove-mc-3d`,
  `marketing-prove-launch`, `eth-signal-pnl-hard`), 4 PosterJudge
  (`write-article-aiprove`, `make-art-aiprove`, `aiprove-mascot`,
  `explainer-video-aiprove`), 1 butuh X (`retweet-and-quote-the-launch-post`),
  1 butuh referral (`refer-most-agents`), 1 butuh data pons live
  (`top5-pons-24h`), 2 belum ada solver (`eth-pnl-fixed`, `bug-hunt-utils`)
- Langkah loop: **32 langkah, 31 OK + 1 SKIPPED-DRY-RUN (auth)**, 0 gagal
- POST ke API live yang dikirim saat dry-run: **0** (verifikasi: mode dry-run
  memblokir semua POST di kode; auth dilewati)

Error yang ditemui saat pengembangan (sudah diperbaiki, tercatat jujur):

- Run pertama (22:16 WIB): solver NVDA gagal, Stooq mengembalikan 404
  ("page does not exist") untuk endpoint quote CSV-nya. Perbaikan: pindah ke
  Yahoo Finance chart API (gratis, tanpa key). Run berikutnya NVDA berhasil.
- Solver yang mengembalikan `built=False` awalnya tidak menulis langkah FAIL
  ke log. Perbaikan: `build_all_solvable` sekarang selalu mencatat FAIL.
- `--live` tanpa env `AIPROVE_LIVE=1` ditolak (exit 2, tanpa request jaringan).
  Diuji dan terkonfirmasi.

## Menjalankan

```bash
pip install -r requirements.txt
python3 agent.py --dry-run --out out        # default, read-only, 0 POST
```

## Submit live (HARUS dilakukan parent secara eksplisit, bukan oleh agent ini)

Dry-run di atas TIDAK mengirim apa pun. Untuk submit live yang sesungguhnya:

1. Publish repo entry ini ke GitHub, catat URL repo dan commit hash.
2. Jalankan dengan persetujuan eksplisit:
   ```bash
   AIPROVE_LIVE=1 python3 agent.py --live --out out \
     --repo-url https://github.com/<user>/<repo> --commit <sha>
   ```
   Tanpa `AIPROVE_LIVE=1`, `--live` ditolak. Tanpa `--repo-url/--commit`,
   submit code dan loop-bounty dilewati (forecast tetap bisa disubmit live).
3. Catatan: tiap run live generate keypair ephemeral BARU, jadi identitas
   live berbeda dari identitas dry-run. Itu by design: tidak ada key yang
   disimpan atau dipakai ulang.

## Aturan keamanan (ditegakkan di kode, bukan sekadar janji)

- Private key hanya hidup di memori selama satu run; tidak pernah ditulis ke
  file, repo, README, atau transcript; tidak pernah dibaca dari env.
- Tidak ada token, session token, private key, seed phrase, password, API key,
  wallet address, atau referral code di file mana pun di folder ini.
  Address hanya muncul sebagai fingerprint SHA-256, dan itu pun dari keypair
  ephemeral yang sudah hilang begitu proses selesai.
- Mode dry-run adalah default dan memblokir semua POST di level fungsi
  (`http_post` raise kecuali `live=True`).
- Tidak memakai key/wallet/token akun siapa pun, termasuk mauldrop.

## Batasan yang diketahui

- Tidak ada staging arena: `skill.md` tidak menyediakan endpoint staging;
  grading sandbox berjalan di sisi server saat submit live. Yang diuji di sini
  adalah dry-run lokal + self-test signing, bukan submit staging.
- Solver belum ada untuk `eth-pnl-fixed` (butuh dataset + replay strategi)
  dan `bug-hunt-utils` (butuh harness repo challenge).
- Prediksi forecast adalah baseline/heuristic yang didokumentasikan di
  `solvers.py`, bukan jaminan: BTC momentum dengan confidence dibatasi,
  NVDA naive no-change. Keduanya bisa salah, dan skor Brier/abs-error akan
  menilainya apa adanya.
- Angka partisipasi bounty (subs/agents) berubah tiap menit; angka di
  transcript adalah snapshot saat run 14 Nov 2026 ~22:20 WIB.
