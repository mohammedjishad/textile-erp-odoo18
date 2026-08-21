# Copyright 2016-2017 LasLabs Inc.
# Copyright 2017-2018 Tecnativa - Jairo Llopis
# Copyright 2018-2019 Tecnativa - Alexandre Díaz
# Copyright 2021 ITerra - Sergey Shebanin
# Copyright 2023 Onestein - Anjeel Haria
# Copyright 2023 Taras Shabaranskyi
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html).

{
    "name": "Web Responsive",
    "summary": "Responsive web client, community-supported",
    "version": "18.0.1.0.6",
    "category": "Website",
    "website": "https://github.com/OCA/web",
    "author": "LasLabs, Tecnativa, ITerra, Onestein, "
    "Odoo Community Association (OCA)",
    "license": "LGPL-3",
    "installable": True,
    "depends": ["web", "web_tour", "mail", "hide_menu_user"],
    "development_status": "Production/Stable",
    "maintainers": ["Tardo", "SplashS"],
    "excludes": ["web_enterprise"],
    "data": [
        "views/res_users_views.xml",
    ],
    "assets": {
        "web._assets_primary_variables": {
            "/prosevo_web_responsive/static/src/legacy/scss/form_variable.scss",
            "/prosevo_web_responsive/static/src/legacy/scss/primary_variable.scss",
        },
        "web.assets_backend": [
            "prosevo_web_responsive/static/src/lib/fuse/fuse.basic.min.js",
            "/prosevo_web_responsive/static/src/legacy/scss/prosevo_web_responsive.scss",
            "/prosevo_web_responsive/static/src/legacy/scss/big_boxes.scss",
            "/prosevo_web_responsive/static/src/legacy/scss/list_sticky_header.scss",
            "/prosevo_web_responsive/static/src/legacy/js/prosevo_web_responsive.esm.js",
            "/prosevo_web_responsive/static/src/legacy/xml/form_buttons.xml",
            "/prosevo_web_responsive/static/src/legacy/xml/custom_favorite_item.xml",
            "/prosevo_web_responsive/static/src/components/apps_menu_tools.esm.js",
            "/prosevo_web_responsive/static/src/components/apps_menu/*",
            "/prosevo_web_responsive/static/src/components/apps_menu_item/*",
            "/prosevo_web_responsive/static/src/components/menu_canonical_searchbar/*",
            "/prosevo_web_responsive/static/src/components/menu_odoo_searchbar/*",
            "/prosevo_web_responsive/static/src/components/menu_fuse_searchbar/*",
            "/prosevo_web_responsive/static/src/components/menu_searchbar/*",
            "/prosevo_web_responsive/static/src/components/hotkey/*",
            "/prosevo_web_responsive/static/src/components/file_viewer/*",
            "/prosevo_web_responsive/static/src/components/chatter/*",
            "/prosevo_web_responsive/static/src/components/control_panel/*",
            "/prosevo_web_responsive/static/src/components/command_palette/*",
            "/prosevo_web_responsive/static/src/views/form/*",
        ],
        "web.assets_clickbot": [
            "/prosevo_web_responsive/static/src/clickbot/clickbot.esm.js",
        ],
        "web.qunit_suite_tests": [
            "/prosevo_web_responsive/static/tests/apps_menu_tests.esm.js",
            "/prosevo_web_responsive/static/tests/apps_menu_search_tests.esm.js",
        ],
    },
    "sequence": 1,
}
