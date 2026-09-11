import { defineConfig } from "vitepress";

const sourceLink = "https://github.com/it-at-m/dienstleistungsfinder-ki";

export default defineConfig({
  title: "Dienstleistungsfinder KI",
  description:
    "Technical documentation for the AI-supported municipal service search",
  cleanUrls: true,
  lastUpdated: true,
  base: "/dienstleistungsfinder-ki/",
  head: [["meta", { name: "theme-color", content: "#005a9c" }]],
  locales: {
    root: { label: "English", lang: "en", link: "/" },
    de: {
      label: "Deutsch",
      lang: "de-DE",
      link: "/de/",
      title: "Dienstleistungsfinder KI",
      description:
        "Technische Dokumentation der KI-gestützten Dienstleistungssuche",
      markdown: {
        container: {
          tipLabel: "TIPP",
          warningLabel: "WARNUNG",
          dangerLabel: "GEFAHR",
          infoLabel: "INFO",
          detailsLabel: "Details",
        },
        codeCopyButton: { tooltipText: "Code kopieren", copiedText: "Kopiert" },
      },
    },
  },
  themeConfig: {
    siteTitle: "Dienstleistungsfinder KI",
    locales: {
      root: {
        nav: [
          { text: "Guide", link: "/architecture" },
          { text: "API", link: "/search-api" },
          { text: "Source", link: sourceLink },
        ],
        sidebar: [
          {
            text: "Technical documentation",
            items: [
              { text: "Overview", link: "/" },
              { text: "System architecture", link: "/architecture" },
              { text: "Local development", link: "/local-development" },
              { text: "Indexing pipeline", link: "/indexing-pipeline" },
              { text: "Search and API", link: "/search-api" },
              { text: "MCP server", link: "/mcp-server" },
              { text: "Frontend and deployment", link: "/frontend-deployment" },
            ],
          },
        ],
        outline: { level: [2, 3], label: "On this page" },
        footer: {
          message: "Technical documentation for Dienstleistungsfinder KI",
          copyright: "Released under the MIT License",
        },
      },
      de: {
        nav: [
          { text: "Leitfaden", link: "/de/architektur" },
          { text: "API", link: "/de/suche-api" },
          { text: "Quellcode", link: sourceLink },
        ],
        sidebar: [
          {
            text: "Technische Dokumentation",
            items: [
              { text: "Übersicht", link: "/de/" },
              { text: "Systemarchitektur", link: "/de/architektur" },
              { text: "Lokale Entwicklung", link: "/de/lokale-entwicklung" },
              { text: "Indizierungspipeline", link: "/de/indexing-pipeline" },
              { text: "Suche und API", link: "/de/suche-api" },
              { text: "MCP-Server", link: "/de/mcp-server" },
              {
                text: "Frontend und Bereitstellung",
                link: "/de/frontend-bereitstellung",
              },
            ],
          },
        ],
        outline: { level: [2, 3], label: "Auf dieser Seite" },
        lastUpdatedText: "Zuletzt aktualisiert",
        docFooter: { prev: "Vorherige Seite", next: "Nächste Seite" },
        returnToTopLabel: "Nach oben",
        sidebarMenuLabel: "Menü",
        darkModeSwitchLabel: "Darstellung",
        lightModeSwitchTitle: "Zum hellen Design wechseln",
        darkModeSwitchTitle: "Zum dunklen Design wechseln",
        langMenuLabel: "Sprache ändern",
        notFound: {
          title: "SEITE NICHT GEFUNDEN",
          quote: "Die angeforderte Seite konnte nicht gefunden werden.",
          linkLabel: "Zur Startseite",
          linkText: "Zur Startseite",
        },
        footer: {
          message: "Technische Dokumentation für Dienstleistungsfinder KI",
          copyright: "Veröffentlicht unter der MIT-Lizenz",
        },
      },
    },
    search: {
      provider: "local",
      options: {
        locales: {
          de: {
            translations: {
              button: {
                buttonText: "Suchen",
                buttonAriaLabel: "Dokumentation durchsuchen",
              },
              modal: {
                displayDetails: "Detaillierte Liste anzeigen",
                resetButtonTitle: "Suche zurücksetzen",
                backButtonTitle: "Suche schließen",
                noResultsText: "Keine Ergebnisse für",
                footer: {
                  selectText: "auswählen",
                  selectKeyAriaLabel: "Eingabetaste",
                  navigateText: "navigieren",
                  navigateUpKeyAriaLabel: "Pfeil nach oben",
                  navigateDownKeyAriaLabel: "Pfeil nach unten",
                  closeText: "schließen",
                  closeKeyAriaLabel: "Escape",
                },
              },
            },
          },
        },
      },
    },
    socialLinks: [{ icon: "github", link: sourceLink }],
  },
});
