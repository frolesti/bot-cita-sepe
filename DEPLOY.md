# Guia de Desplegament (Bot Cita SEPE)

Aquesta guia explica com pujar el bot a un servei al núvol perquè funcioni 24/7.

## 1. Arquitectura

Hem configurat un entorn **Dockeritzat** que executa dos processos dins del mateix contenidor:
1.  **Web (Flask):** Perquè puguis afegir/treure DNI i veure l'estat.
2.  **Worker (Bot):** Un procés de fons que va comprovant cites contínuament.

Això es gestiona automàticament amb `supervisord`.

## 2. On allotjar-ho?

Com que el bot utilitza **Google Chrome**, necessita més memòria RAM que una web normal. No pots utilitzar les capes gratuïtes més bàsiques (com els 512MB de Render Free Tier) perquè Chrome es penjarà (crash `Signal 9`).

Recomanació **Mínima**: 1GB - 2GB RAM.

### Opció A: Render.com (Més fàcil)
1.  Crea un compte a [Render](https://render.com).
2.  Connecta el teu repositori de GitHub.
3.  Selecciona "New Web Service".
4.  **Important:** A "Instance Type", has de triar un pla de pagament.
    *   **Pla Starter (7$/mes):** Té 512MB. És molt just. Pot funcionar si poses `MAX_WORKERS=1` a les variables d'entorn, però és arriscat.
    *   **Pla Standard (25$/mes):** D'1 a 2 GB RAM. Aquest és el **recomanat** per a una estabilitat total.

### Opció B: DigitalOcean / Hetzner (Més barat, requereix saber Linux)
1.  Lloga un "Droplet" (VPS) amb Docker instal·lat.
    *   Preu: ~6-12€/mes per 2GB RAM.
2.  Clona el teu codi al servidor.
3.  Executa: `docker compose up --build -d`.

### Opció C: Fly.io (Intermedi)
Ofereix contenidors amb mides de RAM personalitzables. Pots ajustar a 1024MB o 2048MB per un preu ajustat (aprox. 10-15$).

## 3. Costos estimats en funció dels usuaris

El cost NO depèn directament del nombre d'usuaris, sinó de la **memòria RAM** necessària per obrir navegadors Chrome en paral·lel.

| Usuaris Actius | RAM Necessària | Cost Aprox (Render) | Cost Aprox (VPS Propi) |
| :--- | :--- | :--- | :--- |
| **1 - 10** | 1 GB | ~25 $/mes (Standard) | ~6 €/mes |
| **10 - 50** | 2 GB | ~25 $/mes (Standard) | ~12 €/mes |
| **50 - 200** | 4 GB | ~85 $/mes (Pro) | ~20 €/mes |

*Nota: Amb un sol servidor de 2GB pots gestionar 50 usuaris fàcilment, ja que el bot comprova els usuaris d'un en un (o de 2 en 2), no tots a la vegada instantàniament.*

## 4. Variables d'Entorn Necessàries

Quan configuris el servei, afegeix aquestes variables:

*   `MAIL_USERNAME`: El teu gmail.
*   `MAIL_PASSWORD`: La contrasenya d'aplicació de Google.
*   `MAX_WORKERS`: **Important.** Valors recomanats:
    *   Si tens 512MB RAM: `1` (molt lent però segur)
    *   Si tens 1GB RAM: `1` o `2`
    *   Si tens 2GB RAM: `3` o `4`

## 5. Persistència de Dades

**ATENCIÓ:** En serveis com Render o Fly.io, quan redeplegues una nova versió del codi, **s'esborren els fitxers locals**. Això vol dir que la llista de DNIs (`state.json`) es perdrà cada cop que actualitzis.

*   **Solució Render:** Afegeix un "Disk" (Persistent Disk) i munta'l a la carpeta `/app/data`. Això costa un extra petit (aprox 1$/mes per GB).
*   **Solució VPS:** Docker Volumes (gratuït, ve inclòs al disc del servidor).

---

### Resum per posar-ho en marxa JA:
Si vols la via ràpida i tens pressupost (~25€/mes):
1. Puja aquest codi a GitHub.
2. Ves a Render.com -> New Web Service.
3. Tria el pla Standard (2GB RAM).
4. Afegeix un Persistent Disk muntat a `/app/data`.
5. Posa les variables d'entorn del mail.
6. Prem Deploy.
