# PeBrief: rezultate măsurate

*25 noiembrie 2026. Laptop i7-9750H, totul pe CPU.*

## Setul de test

Clipuri TikTok verticale reale, cu creatori care vorbesc în engleză (din `drive-download-…zip`), peste care am pus:

- **logo-ul inventat „Brisa Zero”**, mișcat ca un produs ținut în mână: lățime 16–42% din cadru, rotație ±22°, perspectivă până la 14%, blur până la σ=1,6, lumină 0,7–1,15×, tremur. Unul sau două intervale; total 0 s, 1–2,5 s (sub pragul de 3 s) sau 3,5–7 s;
- **un logo-capcană „VOLTA”** în 30% din clipuri, care nu trebuie numărat (un clip are oricum logo-ul Supabase pe ecran);
- **voce românească TTS** (Alina sau Emil, viteză −10%…+15%), amestecată cu sunetul original în engleză la volum 8–25%. Scenariile: spune ambele fraze, spune „Brisa” în loc de „Brisa Zero”, uită „fără zahăr”, nu spune nimic, plus un cuvânt interzis (alcool, Cola, gratis) în 30% din clipuri;
- **descrieri** cu sau fără `#ad` și `#brisazero`.

Adevărul e cunoscut cadru cu cadru. Regulile verificate sunt 9 pe clip: durata 10–30 s, logo ≥ 3 s, 2 fraze cerute, 3 cuvinte interzise, 2 hashtag-uri.

## Cele trei seturi și ordinea în care le-am văzut

| Set | Clipuri | Rolul |
| --- | --- | --- |
| reglaj (`clips`, seed 7) | 40 | pe el am ales metodele și pragurile |
| nevăzut (`holdout`, seed 2027, alte propoziții) | 30 | a arătat două probleme reale (mai jos), pe care le-am reparat |
| final (`final`, seed 99, propoziții scrise după înghețarea codului) | 30 | rulat o dată cu codul înghețat, apoi încă o reparație la logo, spusă explicit |

## Rezultatul principal

| | Reglaj (40) | Nevăzut (30) | **Final, cod înghețat (30)** |
| --- | --- | --- | --- |
| Verdict complet corect (toate cele 9 verificări) | 40/40 | 27/30 | **27/30** |
| **Clipuri aprobate deși nu trebuiau** | 0 | 0 | **0** |
| Clipuri bune respinse | 0 | 1 | 0 |
| Verificări individuale corecte | 360/360 | 267/270 | 267/270 |
| Logo pe cadre: precizie / recall | 0,95 / 0,96 | 0,95 / 0,86 | 0,95 / 0,94 |
| Eroare la secundele de logo (mediană / medie) | 0,08 / 0,10 s | 0,11 / 0,41 s | 0,08 / 0,19 s |
| Timp (CPU) | 17 s / clip | 18 s / clip | 17 s / clip (~1,1 s per secundă de video) |

**Toate greșelile rămase pe setul final, cu codul înghețat:**
- **c016:** whisper a alunecat pe vorbirea în engleză din fundal. Fraza cerută e marcată ca lipsă, deși a fost spusă. Verificarea greșește în direcția sigură (respinge, nu aprobă); clipul pica oricum din alt motiv.
- **c028:** „Brisa Zero” a fost auzit „biza zero”, deci fraza e marcată ca lipsă. Tot în direcția sigură; clipul pica oricum din alt motiv.
- **c015:** logo-ul a fost numărat 3,2 s în loc de 1,9 s, din cauza unor potriviri false pe texturi și pe logo-ul-capcană. Clipul a picat oricum din alt motiv, dar verificarea de logo era greșită în direcția periculoasă. **Reparat după rularea finală** (verificare fotometrică, mai jos). Cu reparația, logo-ul pe setul final e **30/30**, dar setul final nu mai e complet nevăzut pentru reparația asta.

## Ce am schimbat pe baza măsurătorilor

| Schimbarea | Înainte → după | Pe ce set am măsurat |
| --- | --- | --- |
| **Fără indiciu de vocabular pentru whisper.** Cu `initial_prompt = "Brisa Zero, fără zahăr"`, la c000 creatorul a spus doar „Brisa”, iar whisper a „auzit” de trei ori „Brisa Zero, fără zahăr” (halucinație) | 1 aprobare greșită → 0 | reglaj |
| Cadre analizate la 1024 px în loc de 720 | recall logo 0,89 → 0,95; verdict logo 38 → 40/40 | reglaj |
| Whisper `medium` în loc de `small` | verdict complet 37 → 40/40; „alcool” ratat de 2 ori → 0 | reglaj |
| Cuvinte interzise: prag 0,8, forme flexionate, cuvinte despărțite („alt col”), „Coca-Cola” spart în tokeni; cuvintele scurte (< 5 litere) rămân stricte, ca „col” să nu declanșeze „Cola” | vezi testele unitare | reglaj + teste |
| **Frazele cerute, aliniate cuvânt cu cuvânt** în loc de șir lipit. Înainte, „brisa, e fără zahăr” trecea drept „Brisa Zero” („brisae” ≈ „brisazero”) | 5 fraze aprobate greșit → 0 | nevăzut |
| Logo pe 3 scări (360/180/100 px) | recall pe nevăzut 0,68 → 0,86; verdict logo 25 → 28/30 | reglaj + nevăzut |
| **Verificare fotometrică a logo-ului:** zona găsită e readusă în forma logo-ului și comparată pixel cu pixel (corelație normalizată, prag 0,6). Pe setul de reglaj, detecțiile adevărate au ≥ 0,93, iar cele false ≤ 0,35 | logo final 29 → 30/30; nevăzut și reglaj neschimbate | prag ales pe reglaj, efect văzut pe final |

## Ce nu dovedește setul ăsta

- **Logo-ul e lipit digital**, deci plan, fără reflexii și fără curbura dozei. Cea mai importantă măsurătoare următoare: 20–30 de clipuri filmate cu telefonul, cu un produs real ținut în mână, etichetate de mână.
- **Vocea e TTS**, clară. Creatorii reali vorbesc repede, cu argou și cu muzică tare. Setul de test are doar vorbire în engleză pe fundal, nu muzică.
- **Precizia de 0,95 la logo pe cadre** vine mai ales de la margini: verificăm 4 cadre pe secundă, deci intervalul găsit poate depăși cu un cadru (0,25 s) intervalul real. Eroarea mediană la secunde e 0,08 s.
- Un set de 30 de clipuri e mic: „0 aprobări greșite din 100 de clipuri” înseamnă cel mult ~3% la 95% încredere, nu zero.

## Reproducere

```
python eval/make_dataset.py 40
python eval/make_dataset.py 30 --holdout
python eval/make_dataset.py 30 --final
python eval/run_eval.py            # sau --holdout, --final
python eval/logo_only.py final     # doar logo-ul, mai repede
python eval/ncc_stats.py clips     # distribuția corelației pentru prag
```

Rezultatele brute, clip cu clip, sunt în `eval/results*.json`, iar jurnalele în `eval/data/eval-*.log`.
