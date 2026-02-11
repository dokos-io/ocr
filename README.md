# eTransactions

**Rendez votre ERP compatible avec la facturation électronique**

---

> [!ATTENTION]
> **Cette application est en cours de développement actif.** Les fonctionnalités peuvent être incomplètes, instables ou sujettes à des changements majeurs sans préavis. Elle n'est pas destinée à être utilisée en environnement de production pour le moment.


## Présentation

**eTransactions** est une application qui vise à automatiser et sécuriser le cycle de vie des transactions commerciales en intégrant les standards de facturation électronique.

Issue de l'application OCR, elle a été conçue pour répondre aux exigences réglementaires françaises en matière de dématérialisation des factures, tout en restant compatible avec les applications **Dokos** et **ERPNext**.

## Fonctionnalités

### Disponibles

- **Récupération automatique des factures** — Les factures fournisseurs peuvent être déposées manuellement ou récupérées automatiquement depuis une boîte email dédiée.
- **OCR (Reconnaissance Optique de Caractères)** — Extraction automatique des données des documents via **AWS Textract** ou **Mistral OCR**.

### Roadmap

- **Intégration multi-formats** — Prise en charge des factures fournisseurs aux formats **Factur-X**, **CII** et **UBL**.
- **Émission de factures électroniques** — Génération et émission de factures dans l'un des trois formats précités.
- **Connexion à une Plateforme Agréee (PA)** — Envoi et réception sécurisés des factures électroniques via une plateforme agréée (en cours de sélection).

## Compatibilité

| Applications | Supporté |
|-----------|----------|
| Dokos     | ✅        |
| ERPNext   | ✅        |

## Installation

Depuis votre répertoire `frappe-bench`, exécutez les commandes suivantes :

```bash
# Récupération de l'application
bench get-app https://gitlab.com/dokos/etransactions.git

# Installation sur votre site
bench --site [votre-site] install-app etransactions
```

## Contribution

Les contributions sont les bienvenues ! Pour contribuer :

1. Forkez le projet
2. Créez votre branche de fonctionnalité (`git checkout -b feature/ma-fonctionnalite`)
3. Publiez vos changements (`git commit -m 'Ajout de ma fonctionnalité'`)
4. Poussez votre branche (`git push origin feature/ma-fonctionnalite`)
5. Ouvrez une **Merge Request** sur [GitLab](https://gitlab.com/dokos/etransactions)

## Licence

Cette application est distribuée sous licence [**AGPLv3**](https://www.gnu.org/licenses/agpl-3.0.fr.html).

---

<div align="center">

Développé avec ❤️ par [Dokos SAS](https://dokos.io)  

</div>