#import "template/clean-acmart-indonesia.typ": acmart, acmart-ccs, acmart-keywords, acmart-ref, to-string

#let itk = super(sym.suit.spade)

#let title = [
  Pub-Sub Log Aggregator Terdistribusi dengan Idempotent Consumer, Deduplikasi, dan Kontrol Transaksi
]

#let authors = (
  (
    name: [Faiz Ahnaf Samudra Azis],
    email: [11221076\@student.itk.ac.id],
    mark: itk,
  ),
)

#let affiliations = (
  (
    name: [Institut Teknologi Kalimantan],
    mark: itk,
    department: [Program Studi Informatika],
    city: [Balikpapan, Kalimantan Timur, Indonesia],
  ),
)


#let doi = "https://github.com/fzhnf/pub-sub-log-aggregator-v2"

#let keywords = (
  "Sistem Terdistribusi",
  "Publish-Subscribe",
  "Idempotent Consumer",
  "Deduplikasi",
  "Transaksi ACID",
  "Docker Compose",
)

#show: acmart.with(
  title: title,
  authors: authors,
  affiliations: affiliations,
  doi: doi,
  copyright: "cc",
)

// Table styling
#set table(
  inset: 6pt,
  stroke: 0.2pt + luma(64),
  fill: (_, row) => { if row == 0 { luma(240) } else if calc.odd(row) { luma(252) } else { white } },
)
#show table.cell.where(y: 0): set text(weight: "semibold")

// Spacing between figures/tables and paragraphs
#show figure: set block(above: 1.5em, below: 1.5em)

= Abstrak

Laporan ini menyajikan implementasi sistem Pub-Sub Log Aggregator terdistribusi yang berfokus pada jaminan konsistensi data melalui mekanisme idempotent consumer dan kontrol transaksi. Sistem dibangun menggunakan arsitektur microservices dengan empat komponen: Aggregator (FastAPI), Publisher, Broker (Redis), dan Storage (PostgreSQL). Implementasi menerapkan pola idempotent consumer untuk mencapai semantik exactly-once processing, mekanisme deduplikasi persisten menggunakan unique constraint database, serta transaksi ACID dengan isolation level READ COMMITTED. Hasil pengujian menunjukkan sistem mampu memproses lebih dari 20.000 event dengan tingkat duplikasi 35% secara konsisten tanpa terjadi race condition.

#acmart-keywords(keywords)

= Pendahuluan

Sistem terdistribusi modern menghadapi tantangan dalam menjaga konsistensi data ketika komponen-komponen berjalan secara paralel dan komunikasi jaringan tidak selalu reliable @coulouris2012. Arsitektur publish-subscribe (Pub-Sub) menawarkan decoupling antara pengirim dan penerima pesan, namun menimbulkan kompleksitas dalam penanganan duplikasi dan ordering @vanSteen2023.

Laporan ini menyajikan implementasi Pub-Sub Log Aggregator yang mengatasi tantangan tersebut melalui: (1) pola idempotent consumer untuk mencegah pemrosesan ganda, (2) deduplikasi berbasis unique constraint PostgreSQL, dan (3) transaksi ACID untuk menjamin konsistensi data pada operasi konkuren.

= Arsitektur Sistem

Sistem terdiri dari empat komponen yang berjalan dalam jaringan Docker Compose @khannedy2023:

#figure(
  image("assets/system-architecture-diagram.png", width: 90%),
  caption: [Arsitektur sistem Pub-Sub Log Aggregator],
)

+ *Aggregator*: Layanan utama berbasis FastAPI @fastapi_docs2024 yang menyediakan REST API untuk penerimaan event dan menjalankan consumer untuk memproses antrian pesan.

+ *Publisher*: Generator event yang mensimulasikan kondisi jaringan dengan menyuntikkan 35% pesan duplikat untuk menguji mekanisme deduplikasi.

+ *Broker*: Redis @pzn_redis2023 sebagai message queue yang memungkinkan time decoupling antara Publisher dan Aggregator.

+ *Storage*: PostgreSQL 18 sebagai penyimpanan persisten dengan dukungan transaksi ACID dan unique constraint untuk deduplikasi atomik.

== Model Event

Setiap event menggunakan format JSON dengan struktur sebagai berikut:

#figure(
  table(
    columns: 1,
    align: left,
    table.header([Format JSON]),
    [```json
    {
      "topic": "auth.login",
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "timestamp": "2025-12-15T10:30:00Z",
      "source": "user-service",
      "payload": { "user_id": 123, "action": "login_success" }
    }
    ```],
  ),
  caption: [Contoh format Event JSON],
)

Field `event_id` menggunakan UUID v4 untuk menjamin keunikan global, sedangkan `topic` menggunakan format hierarkis (dot notation) untuk pengelolaan namespace.

== API Endpoints
#figure(
  table(
    columns: (auto, auto),
    align: (left, left),
    table.header([Endpoint], [Fungsi]),
    [`GET /health`], [Health check untuk liveness probe],
    [`POST /publish`], [Menerima single event],
    [`POST /publish/batch`], [Menerima batch event dalam satu transaksi],
    [`GET /events`], [Mengambil daftar event berdasarkan topic],
    [`GET /stats`], [Statistik: received, processed, duplicates, uptime],
  ),
  caption: [Daftar API Endpoints],
)

== Skema Database

Database memiliki dua tabel utama:

#figure(
  table(
    columns: 1,
    align: left,
    table.header([Skema SQL]),
    [```sql
    -- Tabel untuk menyimpan event yang sudah diproses
    CREATE TABLE processed_events (
        id SERIAL PRIMARY KEY,
        topic VARCHAR(255) NOT NULL,
        event_id VARCHAR(255) NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL,
        source VARCHAR(255) NOT NULL,
        payload JSONB NOT NULL,
        processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT unique_topic_event UNIQUE (topic, event_id)
    );

    -- Tabel singleton untuk statistik sistem
    CREATE TABLE stats (
        id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        received INTEGER DEFAULT 0,
        unique_processed INTEGER DEFAULT 0,
        duplicate_dropped INTEGER DEFAULT 0,
        started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    ```],
  ),
  caption: [Skema database dengan unique constraint untuk deduplikasi],
)

= Keputusan Desain

== Strategi Idempotency dan Deduplikasi

Dalam sistem terdistribusi, jaringan yang tidak reliable menyebabkan pesan dapat dikirim lebih dari sekali (at-least-once delivery). Untuk mencegah pemrosesan ganda, sistem menerapkan pola Idempotent Consumer @medium_idempotency2025 @medium_deduplication2023.

Pendekatan yang digunakan:
+ Setiap event memiliki identifier unik berupa kombinasi `(topic, event_id)`
+ Database menyimpan record setiap event yang telah diproses
+ Operasi insert menggunakan klausa `ON CONFLICT DO NOTHING` untuk menolak duplikat secara atomik

#figure(
  table(
    columns: 1,
    align: left,
    table.header([Query SQL]),
    [```sql
    INSERT INTO processed_events (topic, event_id, timestamp, source, payload)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (topic, event_id) DO NOTHING
    RETURNING id
    ```],
  ),
  caption: [Query idempotent insert dengan conflict handling],
)

Keunggulan pendekatan ini adalah deduplikasi dilakukan secara atomik di level database, sehingga tidak memerlukan locking eksplisit di level aplikasi.

== Transaksi dan Kontrol Konkurensi

Untuk mencegah race condition pada operasi konkuren, sistem menerapkan transaksi ACID @coulouris2012:

- *Atomicity*: Seluruh batch event berhasil atau gagal secara keseluruhan
- *Consistency*: Unique constraint menjaga invariant tidak ada event duplikat
- *Isolation*: Menggunakan level `READ COMMITTED`
- *Durability*: Data tersimpan di PostgreSQL dengan Docker named volume

#figure(
  table(
    columns: 1,
    align: left,
    table.header([Kode Python]),
    [```python
    async with db.transaction() as conn:
        for event in events:
            is_new = await db.insert_event(conn, event)
        await db.update_stats(conn, received, processed, duplicates)
    ```],
  ),
  caption: [Transaksi atomik untuk pemrosesan batch],
)

=== Pemilihan Isolation Level

Sistem menggunakan `READ COMMITTED` dengan pertimbangan:

#figure(
  table(
    columns: 3,
    align: (left, left, left),
    table.header([Isolation Level], [Keuntungan], [Kerugian]),
    [READ COMMITTED], [Throughput tinggi, tidak ada deadlock], [Mungkin phantom read],
    [REPEATABLE READ], [Mencegah non-repeatable read], [Overhead lebih tinggi],
    [SERIALIZABLE], [Konsistensi maksimal], [Throughput rendah, risiko deadlock],
  ),
  caption: [Perbandingan isolation level],
)

`READ COMMITTED` dipilih karena unique constraint sudah menjamin tidak ada duplicate insert, sehingga tidak memerlukan isolation level yang lebih ketat. Risiko phantom read tidak relevan karena operasi utama adalah insert, bukan select-for-update.

== Ordering dan Reliability

Sistem tidak menjamin total ordering karena biaya koordinasi yang tinggi. Sebagai gantinya, sistem menggunakan partial ordering berbasis timestamp event. Untuk use case log aggregation, kelengkapan data lebih diprioritaskan daripada urutan absolut @vanSteen2023.

Reliability dicapai melalui:
- Persistensi data menggunakan Docker named volumes
- Redis sebagai buffer saat Aggregator tidak tersedia
- Mekanisme deduplikasi yang mencegah reprocessing setelah crash recovery
- Retry dengan exponential backoff dari sisi Publisher

= Analisis Performa

== Hasil Stress Test

Pengujian dilakukan dengan mengirimkan 20.000 event dengan tingkat duplikasi 35%:

#figure(
  table(
    columns: 2,
    align: left,
    table.header([Metrik], [Nilai]),
    [Total Event Dikirim], [20.000],
    [Tingkat Duplikasi], [35%],
    [Event Unik Tersimpan], [13.000],
    [Duplikat Dibuang], [7.000],
    [Throughput], [5.864 event/detik],
    [Waktu Eksekusi], [3,41 detik],
  ),
  caption: [Hasil pengujian stress test],
)

== Hasil Uji Konkurensi

Pengujian dengan 10 worker paralel yang mengirimkan event dengan `event_id` yang sama secara bersamaan:

#figure(
  table(
    columns: 2,
    align: left,
    table.header([Metrik], [Hasil]),
    [Jumlah Worker], [10],
    [Event per Worker], [500],
    [Total Event], [5.000],
    [Total Diproses], [5.000],
    [Waktu Eksekusi], [0,41 detik],
    [Throughput], [12.115 event/detik],
  ),
  caption: [Hasil pengujian konkurensi dengan 10 worker paralel],
)

Hasil ini membuktikan bahwa mekanisme `INSERT ON CONFLICT` dan unique constraint efektif mencegah race condition tanpa memerlukan pessimistic locking.

= Keterkaitan dengan Teori Sistem Terdistribusi

== T1: Karakteristik Sistem Terdistribusi (Bab 1)

Menurut @coulouris2012, sistem terdistribusi memiliki tiga karakteristik utama: konkurensi, ketiadaan jam global, dan kegagalan independen. Sistem Pub-Sub Log Aggregator ini mendemonstrasikan ketiga karakteristik tersebut.

*Konkurensi* ditunjukkan melalui pemrosesan paralel oleh multiple worker yang mengambil pesan dari Redis queue secara bersamaan. Setiap worker berjalan sebagai proses independen yang dapat memproses event tanpa menunggu worker lain.

*Ketiadaan jam global* ditangani dengan tidak bergantung pada sinkronisasi waktu antar komponen. Setiap event membawa timestamp sendiri dari sumber asalnya, dan sistem tidak mengasumsikan ordering berdasarkan waktu sistem.

*Kegagalan independen* terlihat dari isolasi antar komponen: Publisher dapat terus mengirim pesan ke Redis meskipun Aggregator sedang down. Pesan akan diproses ketika Aggregator kembali online. Hal ini sesuai dengan prinsip loose coupling dalam sistem terdistribusi.

== T2: Arsitektur Publish-Subscribe (Bab 2)

Arsitektur Pub-Sub dipilih karena menyediakan tiga bentuk decoupling @coulouris2012 @nilebits_pubsub2024:

*Space decoupling*: Publisher tidak perlu mengetahui alamat IP atau hostname Aggregator secara langsung. Komunikasi dilakukan melalui Redis broker dengan nama topic sebagai identifier. Ini memungkinkan penambahan atau penggantian consumer tanpa mengubah publisher.

*Time decoupling*: Publisher dapat mengirim pesan kapan saja, tidak perlu menunggu Aggregator online. Pesan tersimpan di Redis queue dan akan diproses ketika consumer tersedia. Fitur ini penting untuk toleransi kegagalan sementara.

*Synchronization decoupling*: Publisher tidak memblokir menunggu respons pemrosesan dari Aggregator. Setelah pesan berhasil dikirim ke broker, publisher dapat melanjutkan pekerjaan lain. Model asinkron ini meningkatkan throughput sistem secara keseluruhan.

Dibandingkan arsitektur client-server tradisional yang memerlukan koneksi langsung dan sinkron, Pub-Sub lebih scalable untuk skenario dengan banyak producer dan consumer.

== T3: Delivery Semantics (Bab 3)

Sistem mengimplementasikan semantik *at-least-once delivery* yang dikombinasikan dengan pola *idempotent consumer* untuk mencapai efek *exactly-once processing* @vanSteen2023.

At-least-once dipilih karena implementasinya lebih sederhana dibandingkan exactly-once delivery yang memerlukan protokol two-phase commit dengan overhead signifikan. Dengan at-least-once, sistem menjamin setiap pesan pasti terkirim minimal sekali, meski mungkin lebih karena retry pada network failure.

Potensi duplikasi diatasi dengan idempotent consumer: setiap event memiliki identifier unik `(topic, event_id)`, dan database menolak insert duplikat melalui unique constraint. Dengan demikian, meski pesan diterima berkali-kali, efek akhirnya sama seolah diproses sekali saja.

Pendekatan ini memberikan trade-off yang baik antara reliability (pesan tidak hilang) dan simplicity (tidak perlu distributed transaction).

== T4: Skema Penamaan (Bab 4)

Identifikasi event menggunakan kombinasi `(topic, event_id)` dengan karakteristik @vanSteen2023:

*Event ID* menggunakan UUID v4 (128-bit random) yang menjamin keunikan global tanpa koordinasi pusat. Probabilitas collision sangat rendah (2^122 kemungkinan), sehingga aman untuk generate secara independen di setiap publisher.

*Topic* menggunakan format hierarkis dengan dot notation (contoh: `auth.login`, `payment.success`, `order.created`). Struktur hierarkis memungkinkan:
- Pengelolaan namespace yang terorganisir
- Filtering berdasarkan prefix (misal: semua topic `auth.*`)
- Pemisahan logical domain dalam satu sistem

Kombinasi `(topic, event_id)` sebagai identifier memungkinkan event_id yang sama digunakan di topic berbeda, memberikan fleksibilitas tanpa mengorbankan uniqueness.

== T5: Ordering (Bab 5)

Sistem tidak menjamin *total ordering* (urutan global yang konsisten di semua consumer) karena trade-off dengan throughput @coulouris2012. Implementasi total ordering memerlukan koordinasi antar node (contoh: Lamport logical clock, vector clock) yang menambah latency.

Sebagai gantinya, sistem menggunakan *partial ordering* berbasis timestamp yang dibawa setiap event. Ordering hanya dijamin dalam scope satu producer untuk satu topic.

Untuk use case log aggregation, pendekatan ini memadai karena:
- Kelengkapan data lebih penting dari urutan absolut
- Log biasanya dianalisis dalam window waktu, bukan urutan strict
- Consumer dapat melakukan sorting berdasarkan timestamp jika diperlukan

Batasan: jika dua event dari producer berbeda memiliki timestamp identik, urutan relatifnya tidak ditentukan.

== T6: Fault Tolerance (Bab 6)

Toleransi kegagalan dicapai melalui beberapa mekanisme @vanSteen2023 @coulouris2012:

*Message buffering*: Redis menyimpan pesan sementara, sehingga jika Aggregator crash, pesan tidak hilang dan dapat diproses setelah recovery.

*Persistent storage*: PostgreSQL menyimpan data ke disk yang di-mount sebagai Docker named volume. Data aman meski container dihapus dan dibuat ulang.

*Crash recovery*: Setelah restart, Aggregator melanjutkan pemrosesan dari queue. Mekanisme deduplikasi mencegah reprocessing event yang sudah tersimpan sebelum crash.

*Retry dengan backoff*: Publisher mengimplementasikan exponential backoff saat gagal mengirim ke broker, mencegah thundering herd saat recovery.

Sistem tidak menangani Byzantine failure (komponen yang berperilaku tidak terduga/jahat), hanya crash failure (komponen berhenti total).

== T7: Konsistensi (Bab 7)

Sistem mencapai model konsistensi berbeda untuk operasi berbeda @vanSteen2023:

*Strong consistency* untuk penyimpanan event: setiap write ke PostgreSQL langsung visible untuk read berikutnya. Unique constraint menjamin tidak ada duplikat.

*Eventual consistency* untuk statistik: update statistik dilakukan dalam transaksi yang sama dengan insert event, namun pembacaan statistik oleh endpoint `/stats` mungkin melihat nilai yang sedang di-update oleh transaksi lain (READ COMMITTED). Ini acceptable karena statistik bersifat informasional.

Penggunaan single PostgreSQL node sebagai source of truth menghindari kompleksitas replikasi dan distributed consensus (Paxos/Raft) yang diperlukan untuk strong consistency pada multiple nodes.

== T8: Desain Transaksi (Bab 8)

Properti ACID diterapkan sepenuhnya @coulouris2012:

*Atomicity*: Pemrosesan batch event dalam satu transaksi database. Jika insert salah satu event gagal (bukan karena duplicate), seluruh batch di-rollback. Tidak ada state parsial yang tersimpan.

*Consistency*: Unique constraint `(topic, event_id)` menjaga database invariant bahwa tidak boleh ada dua event dengan identifier sama. Constraint `CHECK (id = 1)` pada tabel stats menjamin hanya ada satu row statistik.

*Isolation*: Transaksi konkuren tidak saling melihat perubahan yang belum di-commit. Dengan READ COMMITTED, setiap statement dalam transaksi melihat snapshot data yang sudah committed sebelum statement tersebut dimulai.

*Durability*: PostgreSQL menulis ke WAL (Write-Ahead Log) sebelum mengkonfirmasi commit, menjamin data tidak hilang meski terjadi crash setelah commit.

Trade-off: overhead transaksi menurunkan throughput dibanding operasi non-transactional, namun memberikan jaminan konsistensi yang diperlukan untuk sistem produksi.

== T9: Kontrol Konkurensi (Bab 9)

Sistem menggunakan *optimistic concurrency control* melalui unique constraint dan `INSERT ON CONFLICT` @coulouris2012:

```sql
INSERT INTO processed_events (...)
VALUES (...)
ON CONFLICT (topic, event_id) DO NOTHING
```

Pendekatan ini berbeda dari pessimistic locking yang melakukan `SELECT FOR UPDATE` terlebih dahulu:
- *Tidak ada lock eksplisit*: operasi insert langsung mencoba, dan ditolak jika constraint violated
- *Menghindari deadlock*: tidak ada lock untuk ditunggu
- *Throughput tinggi*: tidak ada blocking antar worker

Untuk update statistik, digunakan atomic increment:
```sql
UPDATE stats SET received = received + $1, unique_processed = unique_processed + $2
```

Pattern ini mencegah lost-update tanpa memerlukan row-level locking, karena PostgreSQL menjamin atomicity operasi aritmatika dalam satu statement.

== T10: Orkestrasi dan Keamanan (Bab 10-13)

Orkestrasi menggunakan Docker Compose @khannedy2023 dengan fitur:

*Dependency management*: `depends_on` memastikan PostgreSQL dan Redis running sebelum Aggregator start.

*Internal network*: Semua service berjalan di network internal Compose. Hanya port 8080 Aggregator yang di-expose untuk akses eksternal. PostgreSQL dan Redis tidak memiliki port mapping ke host, mengurangi attack surface.

*Named volumes*: `pg_data` dan `broker_data` menyimpan data persisten. Volume tidak dihapus saat `docker compose down`, hanya saat eksplisit `docker compose down -v`.

*Health check*: Endpoint `/health` digunakan untuk liveness probe, memungkinkan orchestrator mendeteksi service yang unhealthy dan melakukan restart otomatis.

*Observability*: Endpoint `/stats` menyediakan metrik runtime (event received, processed, duplicates, uptime). Logging ke stdout memungkinkan agregasi log dengan `docker compose logs`.

= Kesimpulan

Sistem Pub-Sub Log Aggregator berhasil diimplementasikan dengan memenuhi seluruh kriteria:
- Idempotency dan deduplikasi berfungsi dengan benar (7.000 duplikat terdeteksi dari 20.000 event)
- Kontrol konkurensi mencegah race condition pada 10 worker paralel
- Persistensi data terjamin melalui Docker named volumes
- Throughput memenuhi target performa (≥20.000 event dengan ≥30% duplikasi)

Implementasi ini mendemonstrasikan penerapan konsep sistem terdistribusi dari Bab 1 hingga 13, dengan penekanan pada transaksi dan kontrol konkurensi (Bab 8-9) melalui penggunaan ACID properties dan optimistic concurrency control.

= Lampiran

== Link Video Demo

#link("https://youtu.be/AcT1KDS0pMc")[YouTube - Video Demo Pub-Sub Log Aggregator]

= Ucapan Terima Kasih

Terima kasih kepada Bapak Riska Kurniyanto Abdullah, S.T., M.Kom. selaku dosen pengampu mata kuliah Sistem Terdistribusi di Program Studi Informatika, Institut Teknologi Kalimantan.

#bibliography("refs.bib", title: "Daftar Pustaka", style: "apa_indonesia.csl")
