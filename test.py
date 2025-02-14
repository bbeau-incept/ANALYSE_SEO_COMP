import streamlit as st
import os
import re
import csv
import glob
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime

# ------------------------------------------------------------------------
# 1) General Settings (comme avant)
# ------------------------------------------------------------------------
SITEMAP_URL = "https://www.officeeasy.fr/sitemap.xml"
OLD_URLS_FILE = "old_sitemap_urls.txt"
CATEGORIES_STATS_FILE = "sitemap_categories.csv"

PAGES_PRODUITS_IN_OUT_CSV = "pages_produits_in_out.csv"          # résumé (nombre IN/OUT)
PAGES_PRODUITS_IN_OUT_LIST_CSV = "pages_produits_in_out_list.csv" # liste détaillée IN/OUT

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

CATEGORIES = {
    "CATEGORIE": (
        r"/(?:telephone-conference|guides|casque-telephonique|telephone-filaire|"
        r"talkie-walkie|ecran-affichage-dynamique-et-publicitaire|passerelles-switch|"
        r"telephonie-mobile|informatique|alarmes-securite)(?:/|\.html)"
    ),
    "autre": (
        r"/(?:mentions-legales|qui-sommes-nous|vos-achats-rembourses|modalites-paiement|"
        r"livraison-express|modalites-livraison|engagements|enable-cookies|cgv|garantie-pro|"
        r"10-jours-essai|reprise-materiel|retours-sav)$"
    ),
    "pages_produits": r"\.html$"  # URLs finissant par .html
}
FALLBACK_CATEGORY = "brand_or_content"


# ------------------------------------------------------------------------
# 2) Fonctions existantes (analyse sitemap, etc.)
# ------------------------------------------------------------------------
def download_sitemap(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        st.error(f"Error downloading sitemap: {e}")
        return {}

    # Parse XML
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        st.error(f"Error parsing XML: {e}")
        return {}

    namespace = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    url_elements = root.findall(f".//{namespace}url")

    url_dict = {}
    for url_elem in url_elements:
        loc = url_elem.find(f"{namespace}loc")
        lastmod = url_elem.find(f"{namespace}lastmod")
        if loc is not None and loc.text:
            url_text = loc.text.strip()
            lastmod_text = lastmod.text.strip() if (lastmod is not None and lastmod.text) else None
            url_dict[url_text] = lastmod_text

    return url_dict

def load_old_urls(file_path):
    if not os.path.exists(file_path):
        return set()
    with open(file_path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def save_urls(file_path, urls):
    with open(file_path, "w", encoding="utf-8") as f:
        for url in sorted(urls):
            f.write(url + "\n")

def categorize_url(url, categories, fallback=FALLBACK_CATEGORY):
    for cat_name, pattern in categories.items():
        if re.search(pattern, url):
            return cat_name
    return fallback

def get_urls_by_category(urls, categories, fallback=FALLBACK_CATEGORY):
    cat_dict = {cat_name: [] for cat_name in categories}
    cat_dict[fallback] = []

    for url in urls:
        cat_name = categorize_url(url, categories, fallback=fallback)
        cat_dict[cat_name].append(url)

    return cat_dict

def record_categories_stats(csv_path, cat_dict, categories, fallback=FALLBACK_CATEGORY):
    date_str = datetime.now().strftime(DATE_FORMAT)
    row = {"date": date_str}
    total_count = 0
    for cat_name in categories:
        count = len(cat_dict.get(cat_name, []))
        row[cat_name] = count
        total_count += count

    fallback_count = len(cat_dict.get(fallback, []))
    row[fallback] = fallback_count
    total_count += fallback_count
    row["total"] = total_count

    # Append au CSV
    fieldnames = ["date"] + list(categories.keys()) + [fallback, "total"]
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def record_pages_produits_in_out(csv_path, in_pages, out_pages):
    file_exists = os.path.exists(csv_path)
    fieldnames = ["date", "in_pages_produits", "out_pages_produits"]
    row = {
        "date": datetime.now().strftime(DATE_FORMAT),
        "in_pages_produits": len(in_pages),
        "out_pages_produits": len(out_pages),
    }
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def record_pages_produits_in_out_list(csv_path, in_pages, out_pages, url_to_lastmod):
    file_exists = os.path.exists(csv_path)
    fieldnames = ["date", "type", "url", "lastmod"]
    now_str = datetime.now().strftime(DATE_FORMAT)

    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for u in in_pages:
            writer.writerow({
                "date": now_str,
                "type": "IN",
                "url": u,
                "lastmod": url_to_lastmod.get(u) if url_to_lastmod.get(u) else ""
            })
        for u in out_pages:
            writer.writerow({
                "date": now_str,
                "type": "OUT",
                "url": u,
                "lastmod": ""
            })

def save_pages_produits_list(pages_dict):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_name = f"pages_produits_{timestamp}.csv"
    fieldnames = ["url", "lastmod"]
    with open(file_name, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for url, lastmod in pages_dict.items():
            writer.writerow({
                "url": url,
                "lastmod": lastmod if lastmod else ""
            })
    return file_name  # on renvoie le nom du fichier créé

def record_pages_produits_last_analysis(csv_path, in_pages, out_pages, url_to_lastmod):
    """
    Écrit un fichier contenant uniquement les résultats de la dernière analyse.
    Ce fichier est réécrit à chaque nouvelle exécution.
    """
    fieldnames = ["date", "type", "url", "lastmod"]
    now_str = datetime.now().strftime(DATE_FORMAT)

    # Réécriture complète du fichier pour ne garder que la dernière analyse
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for u in in_pages:
            writer.writerow({
                "date": now_str,
                "type": "IN",
                "url": u,
                "lastmod": url_to_lastmod.get(u, "")
            })
        for u in out_pages:
            writer.writerow({
                "date": now_str,
                "type": "OUT",
                "url": u,
                "lastmod": ""
            })

# ------------------------------------------------------------------------
# 3) Fonction principale d'analyse (au lieu de main())
# ------------------------------------------------------------------------
def run_sitemap_analysis():
    """
    Effectue l'analyse, met à jour les CSV, et renvoie:
     - Le nom du fichier dynamique créé pour pages_produits
    """
    url_to_lastmod = download_sitemap(SITEMAP_URL)
    if not url_to_lastmod:
        st.warning("Aucune URL récupérée ou erreur lors du download/parsing.")
        return None

    new_urls = set(url_to_lastmod.keys())
    old_urls = load_old_urls(OLD_URLS_FILE)

    in_urls = new_urls - old_urls
    out_urls = old_urls - new_urls

    # pages_produits
    in_pages_produits = [u for u in in_urls if categorize_url(u, CATEGORIES, FALLBACK_CATEGORY) == "pages_produits"]
    out_pages_produits = [u for u in out_urls if categorize_url(u, CATEGORIES, FALLBACK_CATEGORY) == "pages_produits"]
    PAGES_PRODUITS_LAST_ANALYSIS_CSV = "pages_produits_last_analysis.csv"

    # Enregistrement
    record_pages_produits_in_out(PAGES_PRODUITS_IN_OUT_CSV, in_pages_produits, out_pages_produits)
    record_pages_produits_in_out_list(PAGES_PRODUITS_IN_OUT_LIST_CSV, in_pages_produits, out_pages_produits, url_to_lastmod)
    record_pages_produits_last_analysis(PAGES_PRODUITS_LAST_ANALYSIS_CSV, in_pages_produits, out_pages_produits, url_to_lastmod)
    # Maj historique
    save_urls(OLD_URLS_FILE, new_urls)

    # Stats globales
    cat_dict = get_urls_by_category(new_urls, CATEGORIES, fallback=FALLBACK_CATEGORY)
    record_categories_stats(CATEGORIES_STATS_FILE, cat_dict, CATEGORIES, fallback=FALLBACK_CATEGORY)

    # Fichier dynamique
    pages_produits_dict = {}
    for url in cat_dict.get("pages_produits", []):
        lastmod = url_to_lastmod.get(url)
        pages_produits_dict[url] = lastmod

    filename = save_pages_produits_list(pages_produits_dict)
    st.success(f"Analyse terminée. Fichier créé : {filename}")
    return filename


# ------------------------------------------------------------------------
# 4) Interface Streamlit
# ------------------------------------------------------------------------
def main():
    st.title("Analyse de Sitemap - Pages Produits")

    # --- BOUTON : Lancer le check du sitemap ---
    if st.button("Lancer l'analyse du sitemap"):
        st.info("Analyse en cours...")
        csv_name = run_sitemap_analysis()
        if csv_name:
            st.success(f"Analyse terminée et fichier '{csv_name}' créé.")

    st.write("---")

    # --- AFFICHAGE des tableaux existants (pages_produits_in_out.csv) ---
    st.subheader("Historique résumé IN/OUT (pages_produits_in_out.csv)")
    if os.path.exists(PAGES_PRODUITS_IN_OUT_CSV):
        df_in_out = pd.read_csv(PAGES_PRODUITS_IN_OUT_CSV)
        st.dataframe(df_in_out)
    else:
        st.info("Le fichier pages_produits_in_out.csv n'existe pas encore.")

    # --- AFFICHAGE du CSV categories (sitemap_categories.csv) ---
    st.subheader("Statistiques globales de catégories (sitemap_categories.csv)")
    if os.path.exists(CATEGORIES_STATS_FILE):
        df_categories = pd.read_csv(CATEGORIES_STATS_FILE)
        st.dataframe(df_categories)
    else:
        st.info("Le fichier sitemap_categories.csv n'existe pas encore.")

    st.write("---")

    # --- BOUTON pour télécharger le CSV DÉTAILLÉ (pages_produits_in_out_list.csv) ---
    st.subheader("Téléchargement du CSV détaillé (IN/OUT)")
    if os.path.exists(PAGES_PRODUITS_IN_OUT_LIST_CSV):
        with open(PAGES_PRODUITS_IN_OUT_LIST_CSV, "rb") as f:
            st.download_button(
                label="Télécharger pages_produits_in_out_list.csv",
                data=f,
                file_name=PAGES_PRODUITS_IN_OUT_LIST_CSV,
                mime="text/csv"
            )
    else:
        st.info("Aucun CSV détaillé IN/OUT n'est encore disponible.")

    # --- LISTE DÉROULANTE pour choisir un fichier dynamique pages_produits_YYYY-MM-DD_HH-MM-SS.csv ---
    st.subheader("Téléchargement des CSV dynamiques (pages_produits_...)")
    dynamic_csv_files = sorted(glob.glob("pages_produits_*.csv"))
    if dynamic_csv_files:
        selected_file = st.selectbox("Choisir un fichier à télécharger :", dynamic_csv_files)
        if selected_file:
            # Bouton de téléchargement
            with open(selected_file, "rb") as f:
                st.download_button(
                    label=f"Télécharger {selected_file}",
                    data=f,
                    file_name=selected_file,
                    mime="text/csv"
                )
    else:
        st.info("Aucun fichier pages_produits_*.csv n'existe encore.")


if __name__ == "__main__":
    main()