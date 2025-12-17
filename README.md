# Bot Cita SEPE

Aquest projecte és una eina automatitzada per cercar cites prèvies al SEPE (Servicio Público de Empleo Estatal) per a tràmits d'atur.

## Característiques

*   **Interfície Web**: Gestió senzilla de les cerques mitjançant una web local.
*   **Privacitat**: No utilitza base de dades. Tota la informació es manté en memòria i s'esborra en tancar l'aplicació.
*   **Filtres**: Permet cercar cites presencials o telefòniques.
*   **Notificacions**: (Pendent de configurar SMTP) Envia correus quan troba una cita.

## Instal·lació

1.  Clona el repositori o descarrega el codi.
2.  Instal·la les dependències:
    ```bash
    pip install -r requirements.txt
    ```

## Ús

1.  Executa l'aplicació:
    ```bash
    python run.py
    ```
2.  Obre el navegador a `http://127.0.0.1:5000`.
3.  Introdueix el teu DNI, Codi Postal i Email.
4.  El bot obrirà un navegador (Chrome) per comprovar la disponibilitat.
    *   **NOTA IMPORTANT**: El SEPE utilitza un Captcha. La primera vegada (o cada cop, depenent de la configuració), hauràs de resoldre el Captcha manualment a la finestra que s'obre.

## Dataset de Municipis i Comarques

Aquest projecte inclou un dataset de municipis de Catalunya mapejats a les seves respectives Comarques i Províncies, situat a la carpeta `data/`.

### Fitxers

- **municipis_catalunya.json**: Un fitxer JSON amb un array d'objectes, on cada objecte representa un municipi.
  - Camps: `municipality`, `comarca`, `province`.
- **comarques_catalunya.json**: Un fitxer JSON amb una llista de totes les Comarques úniques de Catalunya.

### Font

Les dades s'han extret de llistats públics de municipis de Catalunya.

### Exemple (JSON)

```json
[
    {
        "municipality": "Abella de la Conca",
        "comarca": "Pallars Jussà",
        "province": "Lleida"
    },
    ...
]
```

## Pujar a GitHub

Si vols pujar aquest codi al teu GitHub:

1.  Crea un **Nou Repositori** a GitHub (buit).
2.  Executa les següents comandes al terminal d'aquest projecte:

```bash
git remote add origin https://github.com/EL_TEU_USUARI/EL_TEU_REPOSITORI.git
git branch -M main
git push -u origin main
```

*(Substitueix `EL_TEU_USUARI` i `EL_TEU_REPOSITORI` per les teves dades reals)*.

## Avís Legal

Aquest programari és per a ús educatiu i personal. L'ús de bots pot anar en contra dels termes de servei de algunes administracions. Utilitza'l sota la teva responsabilitat.
