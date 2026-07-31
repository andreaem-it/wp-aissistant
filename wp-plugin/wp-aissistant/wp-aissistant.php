<?php
/**
 * Plugin Name: WP AIssistant
 * Description: Floating AI chat widget backed by a RAG backend, with automatic site content sync.
 * Version: 1.1.5
 */

if (!defined('ABSPATH')) exit;

define('WPAI_OPTION', 'wpai_settings');
define('WPAI_VERSION', '1.1.5'); // keep in sync with the "Version:" header above

// The backend is a single hosted service (not something each site owner runs), so its URL
// isn't a setting — it's hardcoded here. Override only for local/staging testing by defining
// WPAI_BACKEND_URL in wp-config.php before this plugin loads.
if (!defined('WPAI_BACKEND_URL')) {
    define('WPAI_BACKEND_URL', 'https://wp-aissistant-production.up.railway.app');
}

// Real icons instead of emoji, in the widget and in our wp-admin pages. Loaded from the
// official Font Awesome CDN (cdnjs) rather than self-hosted — simplest to keep current,
// at the cost of one extra external request on every page (incl. customer sites running
// the widget).
define('WPAI_FONTAWESOME_URL', 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css');
define('WPAI_FONTAWESOME_SRI', 'sha512-SnH5WK+bZxgPHs44uWIX+LLJAJ9/2PkPKZ5QiAj6Ta86w+fsb2TkcmfRyVX3pBnMFcV7oQPJkl9QevSCWr3W6A==');

function wpai_opt($key) {
    $opts = get_option(WPAI_OPTION, []);
    return $opts[$key] ?? '';
}

function wpai_widget_title() {
    return wpai_opt('widget_title') ?: 'AI Assistant';
}

function wpai_widget_image() {
    return wpai_opt('widget_image') ?: plugins_url('assets/default-avatar.svg', __FILE__);
}

function wpai_setting($key, $default = '') {
    $value = wpai_opt($key);
    return $value === '' ? $default : $value;
}

function wpai_sanitize_settings($input) {
    $input = is_array($input) ? $input : [];
    $themes = ['light', 'dark', 'auto'];
    $positions = ['right', 'left'];
    $motions = ['subtle', 'playful', 'none'];
    $support_days = array_values(array_intersect(
        array_map('absint', (array) ($input['support_days'] ?? [])),
        [1, 2, 3, 4, 5, 6, 7]
    ));
    $support_start = preg_match('/^\d{2}:\d{2}$/', $input['support_start'] ?? '') ? $input['support_start'] : '09:00';
    $support_end = preg_match('/^\d{2}:\d{2}$/', $input['support_end'] ?? '') ? $input['support_end'] : '18:00';

    return [
        'api_key' => sanitize_text_field($input['api_key'] ?? ''),
        'widget_title' => sanitize_text_field($input['widget_title'] ?? ''),
        'widget_subtitle' => sanitize_text_field($input['widget_subtitle'] ?? ''),
        'widget_welcome' => sanitize_textarea_field($input['widget_welcome'] ?? ''),
        'widget_ai_disclosure' => sanitize_textarea_field($input['widget_ai_disclosure'] ?? ''),
        'widget_launcher_label' => sanitize_text_field($input['widget_launcher_label'] ?? ''),
        'widget_privacy_url' => esc_url_raw($input['widget_privacy_url'] ?? ''),
        'widget_image' => esc_url_raw($input['widget_image'] ?? ''),
        'widget_color' => sanitize_hex_color($input['widget_color'] ?? '') ?: '#635bff',
        'widget_theme' => in_array($input['widget_theme'] ?? '', $themes, true) ? $input['widget_theme'] : 'light',
        'widget_position' => in_array($input['widget_position'] ?? '', $positions, true) ? $input['widget_position'] : 'right',
        'widget_motion' => in_array($input['widget_motion'] ?? '', $motions, true) ? $input['widget_motion'] : 'subtle',
        'support_hours_enabled' => empty($input['support_hours_enabled']) ? '0' : '1',
        'support_days' => $support_days,
        'support_start' => sanitize_text_field($support_start),
        'support_end' => sanitize_text_field($support_end),
    ];
}

// ---- Admin menu: top-level "AI Assistant" with Impostazioni + Sincronizzazione ----

add_action('admin_menu', function () {
    add_menu_page('AI Assistant', 'AI Assistant', 'manage_options', 'wp-aissistant', 'wpai_settings_page', 'dashicons-format-chat', 58);
    add_submenu_page('wp-aissistant', 'Impostazioni', 'Impostazioni', 'manage_options', 'wp-aissistant', 'wpai_settings_page');
    add_submenu_page('wp-aissistant', 'Sincronizzazione', 'Sincronizzazione', 'manage_options', 'wp-aissistant-sync', 'wpai_sync_page');
});

add_action('admin_init', function () {
    register_setting('wpai', WPAI_OPTION, ['sanitize_callback' => 'wpai_sanitize_settings']);
});

// Fetch the current plan + monthly usage from the backend (best-effort; returns null on error).
function wpai_fetch_usage() {
    $key = wpai_opt('api_key');
    if (!$key) return null;
    $res = wp_remote_get(WPAI_BACKEND_URL . '/usage', [
        'timeout' => 8,
        'headers' => ['Authorization' => 'Bearer ' . $key],
    ]);
    if (is_wp_error($res) || wp_remote_retrieve_response_code($res) !== 200) return null;
    return json_decode(wp_remote_retrieve_body($res), true);
}

function wpai_settings_page() {
    $opts = get_option(WPAI_OPTION, []);
    $image = $opts['widget_image'] ?? '';
    $usage = wpai_fetch_usage();
    $pct = $usage && !empty($usage['limit']) ? min(100, round($usage['used'] / $usage['limit'] * 100)) : 0;
    ?>
    <div class="wrap wpai-admin">
        <header class="wpai-admin-hero">
            <div>
                <span class="wpai-eyebrow"><i class="fa-solid fa-wand-magic-sparkles"></i> WP AIssistant</span>
                <h1>Il tuo assistente, con il carattere del tuo brand.</h1>
                <p>Configura aspetto, tono e comportamento del widget. Le modifiche sono visibili nell'anteprima prima di salvarle.</p>
            </div>
            <span class="wpai-version">v<?php echo esc_html(WPAI_VERSION); ?></span>
        </header>
        <nav class="wpai-admin-nav" aria-label="Sezioni AI Assistant">
            <a class="is-active" href="<?php echo esc_url(admin_url('admin.php?page=wp-aissistant')); ?>"><i class="fa-solid fa-sliders"></i> Personalizzazione</a>
            <a href="<?php echo esc_url(admin_url('admin.php?page=wp-aissistant-sync')); ?>"><i class="fa-solid fa-rotate"></i> Sincronizzazione</a>
        </nav>

        <div class="wpai-admin-grid">
        <form method="post" action="options.php">
            <?php settings_fields('wpai'); ?>
            <section class="wpai-admin-card">
                <div class="wpai-card-heading"><span class="wpai-step">01</span><div><h2>Connessione</h2><p>Collega il sito al tuo account WP AIssistant.</p></div></div>
                <label class="wpai-field" for="api_key"><span>API Key</span>
                    <input type="password" id="api_key" name="<?php echo esc_attr(WPAI_OPTION); ?>[api_key]" value="<?php echo esc_attr($opts['api_key'] ?? ''); ?>" autocomplete="off" />
                    <small>La trovi nel pannello operatore, nella sezione Profilo.</small>
                </label>
            </section>

            <section class="wpai-admin-card">
                <div class="wpai-card-heading"><span class="wpai-step">02</span><div><h2>Identità</h2><p>Dai un nome e una voce riconoscibile all'assistente.</p></div></div>
                <div class="wpai-fields-two">
                    <label class="wpai-field" for="widget_title"><span>Nome assistente</span>
                        <input type="text" id="widget_title" data-preview="title" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_title]" value="<?php echo esc_attr($opts['widget_title'] ?? ''); ?>" placeholder="AI Assistant" />
                    </label>
                    <label class="wpai-field" for="widget_subtitle"><span>Stato / sottotitolo</span>
                        <input type="text" id="widget_subtitle" data-preview="subtitle" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_subtitle]" value="<?php echo esc_attr($opts['widget_subtitle'] ?? ''); ?>" placeholder="Di solito risponde subito" />
                    </label>
                </div>
                <label class="wpai-field" for="widget_welcome"><span>Messaggio di benvenuto</span>
                    <textarea id="widget_welcome" data-preview="welcome" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_welcome]" rows="3" placeholder="Ciao! Come posso aiutarti oggi?"><?php echo esc_textarea($opts['widget_welcome'] ?? ''); ?></textarea>
                    <small>Appare all'apertura della chat, prima del primo messaggio.</small>
                </label>
                <label class="wpai-field" for="widget_ai_disclosure"><span>Informativa AI</span>
                    <textarea id="widget_ai_disclosure" data-preview="disclosure" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_ai_disclosure]" rows="2" placeholder="Stai parlando con un assistente virtuale basato su intelligenza artificiale."><?php echo esc_textarea($opts['widget_ai_disclosure'] ?? ''); ?></textarea>
                    <small>Appare in alto nella conversazione. Se hai configurato la Privacy Policy, il relativo consenso viene aggiunto automaticamente.</small>
                </label>
                <div class="wpai-field"><span>Avatar</span><div class="wpai-media-row">
                        <img id="wpai-image-preview" src="<?php echo esc_url($image ?: wpai_widget_image()); ?>" alt="" />
                        <input type="hidden" id="widget_image" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_image]" value="<?php echo esc_attr($image); ?>" />
                        <div><button type="button" class="button" id="wpai-image-select">Scegli immagine</button>
                        <button type="button" class="button button-link-delete" id="wpai-image-clear"<?php echo $image ? '' : ' hidden'; ?>>Rimuovi</button></div>
                </div></div>
            </section>

            <section class="wpai-admin-card">
                <div class="wpai-card-heading"><span class="wpai-step">03</span><div><h2>Look & feel</h2><p>Adatta il widget al design del sito.</p></div></div>
                <div class="wpai-fields-two">
                    <label class="wpai-field" for="widget_color"><span>Colore principale</span><div class="wpai-color-control">
                        <input type="color" id="widget_color" data-preview="color" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_color]" value="<?php echo esc_attr($opts['widget_color'] ?? '#635bff'); ?>" />
                        <output id="wpai-color-value"><?php echo esc_html($opts['widget_color'] ?? '#635bff'); ?></output>
                    </div></label>
                    <label class="wpai-field" for="widget_position"><span>Posizione</span><select id="widget_position" data-preview="position" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_position]">
                        <option value="right"<?php selected($opts['widget_position'] ?? 'right', 'right'); ?>>In basso a destra</option>
                        <option value="left"<?php selected($opts['widget_position'] ?? 'right', 'left'); ?>>In basso a sinistra</option>
                    </select></label>
                    <label class="wpai-field" for="widget_theme"><span>Tema</span><select id="widget_theme" data-preview="theme" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_theme]">
                        <option value="light"<?php selected($opts['widget_theme'] ?? 'light', 'light'); ?>>Chiaro</option>
                        <option value="dark"<?php selected($opts['widget_theme'] ?? 'light', 'dark'); ?>>Scuro</option>
                        <option value="auto"<?php selected($opts['widget_theme'] ?? 'light', 'auto'); ?>>Segui il dispositivo</option>
                    </select></label>
                    <label class="wpai-field" for="widget_motion"><span>Animazioni</span><select id="widget_motion" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_motion]">
                        <option value="subtle"<?php selected($opts['widget_motion'] ?? 'subtle', 'subtle'); ?>>Fluide</option>
                        <option value="playful"<?php selected($opts['widget_motion'] ?? 'subtle', 'playful'); ?>>Vivaci</option>
                        <option value="none"<?php selected($opts['widget_motion'] ?? 'subtle', 'none'); ?>>Disattivate</option>
                    </select></label>
                </div>
                <label class="wpai-field" for="widget_launcher_label"><span>Etichetta del pulsante</span>
                    <input type="text" id="widget_launcher_label" data-preview="launcher" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_launcher_label]" value="<?php echo esc_attr($opts['widget_launcher_label'] ?? ''); ?>" placeholder="Come possiamo aiutarti?" />
                    <small>Lascia vuoto per mostrare soltanto l'icona.</small>
                </label>
            </section>

            <section class="wpai-admin-card">
                <div class="wpai-card-heading"><span class="wpai-step">04</span><div><h2>Disponibilità operatori</h2><p>Decidi quando la chat può passare in tempo reale al supporto umano.</p></div></div>
                <label class="wpai-switch-row" for="support_hours_enabled">
                    <span><strong>Usa gli orari del supporto</strong><small>Fuori orario il visitatore potrà aprire un ticket asincrono.</small></span>
                    <input type="checkbox" id="support_hours_enabled" name="<?php echo esc_attr(WPAI_OPTION); ?>[support_hours_enabled]" value="1"<?php checked($opts['support_hours_enabled'] ?? '0', '1'); ?> />
                </label>
                <div class="wpai-support-schedule" id="wpai-support-schedule">
                    <div class="wpai-field"><span>Giorni attivi</span><div class="wpai-day-picker">
                    <?php
                    $day_labels = [1 => 'Lun', 2 => 'Mar', 3 => 'Mer', 4 => 'Gio', 5 => 'Ven', 6 => 'Sab', 7 => 'Dom'];
                    $selected_days = $opts['support_days'] ?? [1, 2, 3, 4, 5];
                    foreach ($day_labels as $day_value => $day_label) :
                    ?>
                        <label><input type="checkbox" name="<?php echo esc_attr(WPAI_OPTION); ?>[support_days][]" value="<?php echo (int) $day_value; ?>"<?php checked(in_array($day_value, $selected_days, true)); ?> /><span><?php echo esc_html($day_label); ?></span></label>
                    <?php endforeach; ?>
                    </div></div>
                    <div class="wpai-fields-two">
                        <label class="wpai-field" for="support_start"><span>Dalle</span><input type="time" id="support_start" name="<?php echo esc_attr(WPAI_OPTION); ?>[support_start]" value="<?php echo esc_attr($opts['support_start'] ?? '09:00'); ?>" /></label>
                        <label class="wpai-field" for="support_end"><span>Alle</span><input type="time" id="support_end" name="<?php echo esc_attr(WPAI_OPTION); ?>[support_end]" value="<?php echo esc_attr($opts['support_end'] ?? '18:00'); ?>" /></label>
                    </div>
                    <p class="wpai-timezone-note"><i class="fa-solid fa-earth-europe"></i> Fuso orario: <strong><?php echo esc_html(wp_timezone_string()); ?></strong>, configurato nelle impostazioni generali di WordPress.</p>
                </div>
            </section>

            <section class="wpai-admin-card">
                <div class="wpai-card-heading"><span class="wpai-step">05</span><div><h2>Privacy</h2><p>Collega l'informativa mostrata nel widget.</p></div></div>
                <label class="wpai-field" for="widget_privacy_url"><span>URL Privacy Policy</span>
                    <input type="url" id="widget_privacy_url" name="<?php echo esc_attr(WPAI_OPTION); ?>[widget_privacy_url]" value="<?php echo esc_attr($opts['widget_privacy_url'] ?? ''); ?>" placeholder="https://tuosito.it/privacy" />
                </label>
            </section>
            <div class="wpai-savebar"><span>Le modifiche vengono applicate al widget dopo il salvataggio.</span><?php submit_button('Salva modifiche', 'primary', 'submit', false); ?></div>
        </form>
        <aside class="wpai-admin-aside">
            <div class="wpai-preview-card">
                <div class="wpai-preview-label"><span>Anteprima live</span><span class="wpai-live-dot">Live</span></div>
                <div class="wpai-preview-stage" id="wpai-preview-stage">
                    <div class="wpai-preview-window" id="wpai-preview-window">
                        <div class="wpai-preview-header"><img src="<?php echo esc_url(wpai_widget_image()); ?>" alt=""><div><strong><?php echo esc_html(wpai_widget_title()); ?></strong><small><?php echo esc_html(wpai_setting('widget_subtitle', 'Di solito risponde subito')); ?></small></div><i class="fa-solid fa-xmark"></i></div>
                        <div class="wpai-preview-body"><small class="wpai-preview-disclosure"><span class="wpai-preview-disclosure-copy"><?php echo esc_html(wpai_setting('widget_ai_disclosure', 'Stai parlando con un assistente virtuale basato su intelligenza artificiale.')); ?></span><?php echo wpai_opt('widget_privacy_url') ? ' Proseguendo accetti la nostra privacy policy.' : ''; ?></small><span><?php echo esc_html(wpai_setting('widget_welcome', 'Ciao! Come posso aiutarti oggi?')); ?></span></div>
                        <div class="wpai-preview-input">Scrivi un messaggio… <i class="fa-solid fa-arrow-up"></i></div>
                    </div>
                    <div class="wpai-preview-launcher"><span><?php echo esc_html(wpai_setting('widget_launcher_label')); ?></span><i class="fa-solid fa-comment-dots"></i></div>
                </div>
            </div>
            <div class="wpai-admin-card wpai-usage-card">
                <div class="wpai-card-heading"><div><h2><?php echo $usage ? esc_html(ucfirst($usage['plan'] ?: 'Piano attivo')) : 'Stato account'; ?></h2><p><?php echo $usage ? 'Utilizzo del mese corrente' : 'Connessione al servizio'; ?></p></div></div>
                <?php if ($usage) : ?><div class="wpai-usage-numbers"><strong><?php echo (int) $usage['used']; ?></strong><span><?php echo !empty($usage['limit']) ? 'di ' . (int) $usage['limit'] . ' messaggi' : 'messaggi, nessun limite'; ?></span></div>
                    <?php if (!empty($usage['limit'])) : ?><div class="wpai-bar"><div class="wpai-bar-fill<?php echo $pct >= 100 ? ' is-full' : ''; ?>" style="width:<?php echo esc_attr($pct); ?>%"></div></div><small><?php echo (int) $usage['remaining']; ?> messaggi rimanenti</small><?php endif; ?>
                <?php elseif (wpai_opt('api_key')) : ?><p class="wpai-alert">Impossibile recuperare il piano. Verifica l'API Key.</p>
                <?php else : ?><p>Inserisci l'API Key per attivare il widget e visualizzare il consumo.</p><?php endif; ?>
            </div>
        </aside>
        </div>
    </div>
    <?php
}

function wpai_sync_page() {
    ?>
    <div class="wrap wpai-admin">
        <header class="wpai-admin-hero"><div><span class="wpai-eyebrow"><i class="fa-solid fa-arrows-rotate"></i> Knowledge base</span><h1>Contenuti sempre aggiornati.</h1><p>Allinea pagine, articoli<?php echo function_exists('WC') ? ' e prodotti WooCommerce' : ''; ?> con la conoscenza dell'assistente.</p></div><span class="wpai-version">v<?php echo esc_html(WPAI_VERSION); ?></span></header>
        <nav class="wpai-admin-nav" aria-label="Sezioni AI Assistant"><a href="<?php echo esc_url(admin_url('admin.php?page=wp-aissistant')); ?>"><i class="fa-solid fa-sliders"></i> Personalizzazione</a><a class="is-active" href="<?php echo esc_url(admin_url('admin.php?page=wp-aissistant-sync')); ?>"><i class="fa-solid fa-rotate"></i> Sincronizzazione</a></nav>
        <section class="wpai-admin-card wpai-sync-card"><div class="wpai-sync-intro"><div class="wpai-sync-icon"><i class="fa-solid fa-cloud-arrow-up"></i></div><div><h2>Sincronizzazione completa</h2><p>I nuovi contenuti vengono già acquisiti alla pubblicazione. Avvia una sincronizzazione completa dopo l'installazione o quando hai modificato molti contenuti.</p></div></div>
        <?php if (!wpai_opt('api_key')) : ?>
            <div class="wpai-alert">Imposta prima l'<strong>API Key</strong> in Personalizzazione.</div>
        <?php else : ?>
            <div class="wpai-sync-actions"><button class="button button-primary" id="wpai-sync-start"><i class="fa-solid fa-rotate"></i> Sincronizza ora</button><span id="wpai-sync-progress" aria-live="polite">Pronto per iniziare</span></div>
            <div id="wpai-sync-list" class="wpai-sync-list"></div>
        <?php endif; ?>
        </section>
    </div>
    <?php
}

add_action('admin_enqueue_scripts', function ($hook) {
    // settings page needs the media picker
    if ($hook === 'toplevel_page_wp-aissistant') {
        wp_enqueue_media();
        wp_enqueue_script('wpai-admin-settings', plugins_url('assets/admin-settings.js', __FILE__), ['jquery'], WPAI_VERSION, true);
        wp_localize_script('wpai-admin-settings', 'WPAI_ADMIN', ['defaultImage' => plugins_url('assets/default-avatar.svg', __FILE__)]);
    }
    // sync page needs the realtime sync script
    if ($hook === 'ai-assistant_page_wp-aissistant-sync') {
        wp_enqueue_script('wpai-admin-sync', plugins_url('assets/admin-sync.js', __FILE__), ['jquery'], WPAI_VERSION, true);
        wp_localize_script('wpai-admin-sync', 'WPAI_SYNC', [
            'ajaxUrl' => admin_url('admin-ajax.php'),
            'nonce' => wp_create_nonce('wpai_sync'),
        ]);
    }
    // small shared admin CSS on our pages
    if (strpos((string) $hook, 'wp-aissistant') !== false) {
        wp_enqueue_style('wpai-fontawesome', WPAI_FONTAWESOME_URL, [], null);
        wp_enqueue_style('wpai-admin', plugins_url('assets/admin.css', __FILE__), [], WPAI_VERSION);
    }
});

// Subresource integrity on the Font Awesome CDN tag, wherever it's enqueued.
add_filter('style_loader_tag', function ($tag, $handle) {
    if ($handle !== 'wpai-fontawesome') return $tag;
    return str_replace(' rel=', ' integrity="' . WPAI_FONTAWESOME_SRI . '" crossorigin="anonymous" referrerpolicy="no-referrer" rel=', $tag);
}, 10, 2);

// ---- Floating chat widget ----

add_action('wp_enqueue_scripts', function () {
    if (!wpai_opt('api_key')) return;
    wp_enqueue_style('wpai-fontawesome', WPAI_FONTAWESOME_URL, [], null);
    wp_enqueue_style('wpai-chat', plugins_url('assets/chat-widget.css', __FILE__), [], WPAI_VERSION);
    wp_enqueue_script('wpai-chat', plugins_url('assets/chat-widget.js', __FILE__), [], WPAI_VERSION, true);
    wp_localize_script('wpai-chat', 'WPAI', [
        'backendUrl' => rtrim(WPAI_BACKEND_URL, '/'),
        'apiKey' => wpai_opt('api_key'),
        'title' => wpai_widget_title(),
        'image' => wpai_widget_image(),
        'ajaxUrl' => admin_url('admin-ajax.php'),
        'cartNonce' => wp_create_nonce('wpai_cart'),
        'cartUrl' => function_exists('wc_get_cart_url') ? wc_get_cart_url() : '',
        'loggedIn' => is_user_logged_in(),
        'privacyUrl' => wpai_opt('widget_privacy_url'),
        'subtitle' => wpai_setting('widget_subtitle', 'Di solito risponde subito'),
        'welcome' => wpai_setting('widget_welcome', 'Ciao! Come posso aiutarti oggi?'),
        'aiDisclosure' => wpai_setting('widget_ai_disclosure', 'Stai parlando con un assistente virtuale basato su intelligenza artificiale.'),
        'launcherLabel' => wpai_setting('widget_launcher_label'),
        'color' => wpai_setting('widget_color', '#635bff'),
        'theme' => wpai_setting('widget_theme', 'light'),
        'position' => wpai_setting('widget_position', 'right'),
        'motion' => wpai_setting('widget_motion', 'subtle'),
        'support' => [
            'enabled' => wpai_setting('support_hours_enabled', '0') === '1',
            'days' => array_map('intval', (array) wpai_setting('support_days', [1, 2, 3, 4, 5])),
            'start' => wpai_setting('support_start', '09:00'),
            'end' => wpai_setting('support_end', '18:00'),
            'timezone' => wp_timezone_string(),
        ],
        // The Origin/Referer header the backend would otherwise fall back to never carries a
        // path, so a subdirectory install (e.g. example.com/shop/) would build a wrong
        // order-lookup callback URL. Send the real site URL explicitly instead.
        'siteUrl' => home_url(),
    ]);
});

// Add a product from a chat card through WooCommerce itself. The widget only shows a
// success state after WC()->cart->add_to_cart() has returned a real cart item key.
function wpai_add_to_cart() {
    check_ajax_referer('wpai_cart', 'nonce');
    if (!function_exists('wc_get_product') || !function_exists('WC')) {
        wp_send_json_error(['message' => 'WooCommerce non è disponibile.'], 503);
    }

    $product_url = esc_url_raw(wp_unslash($_POST['product_url'] ?? ''));
    $product_id = $product_url ? url_to_postid($product_url) : 0;
    $product = $product_id ? wc_get_product($product_id) : false;
    if (!$product || $product->get_status() !== 'publish') {
        wp_send_json_error(['message' => 'Prodotto non disponibile.'], 404);
    }
    if ($product->is_type(['variable', 'grouped', 'external'])) {
        wp_send_json_error([
            'message' => 'Scegli prima le opzioni del prodotto.',
            'product_url' => get_permalink($product_id),
        ], 409);
    }
    if (!$product->is_purchasable() || !$product->is_in_stock()) {
        wp_send_json_error(['message' => 'Questo prodotto non è acquistabile al momento.'], 409);
    }

    if (function_exists('wc_load_cart') && (!WC()->cart || !WC()->session)) {
        wc_load_cart();
    }
    $cart_item_key = WC()->cart ? WC()->cart->add_to_cart($product_id, 1) : false;
    if (!$cart_item_key) {
        wp_send_json_error(['message' => 'Non è stato possibile aggiungere il prodotto.'], 409);
    }

    ob_start();
    woocommerce_mini_cart();
    $mini_cart = ob_get_clean();
    $fragments = apply_filters('woocommerce_add_to_cart_fragments', [
        'div.widget_shopping_cart_content' => '<div class="widget_shopping_cart_content">' . $mini_cart . '</div>',
    ]);

    wp_send_json_success([
        'message' => 'Aggiunto al carrello',
        'cart_count' => WC()->cart->get_cart_contents_count(),
        'cart_url' => wc_get_cart_url(),
        'fragments' => $fragments,
        'cart_hash' => WC()->cart->get_cart_hash(),
    ]);
}
add_action('wp_ajax_wpai_add_to_cart', 'wpai_add_to_cart');
add_action('wp_ajax_nopriv_wpai_add_to_cart', 'wpai_add_to_cart');

// ---- Content builders ----

function wpai_build_post_content($post) {
    $text = $post->post_title . "\n\n" . wp_strip_all_tags($post->post_content);

    if ($post->post_type === 'product' && function_exists('wc_get_product')) {
        $product = wc_get_product($post->ID);
        if ($product) {
            $text .= "\n\nPrezzo: " . $product->get_price() . "\nSKU: " . $product->get_sku();
            $text .= "\nDisponibilità: " . $product->get_stock_status();
            if ($product->get_short_description()) {
                $text .= "\nDescrizione breve: " . wp_strip_all_tags($product->get_short_description());
            }
            $categories = wp_get_post_terms($post->ID, 'product_cat', ['fields' => 'names']);
            if (!is_wp_error($categories) && $categories) {
                $text .= "\nCategorie: " . implode(', ', $categories);
            }
        }
    }

    return $text;
}

function wpai_build_site_info_content() {
    $lines = [
        get_bloginfo('name'),
        get_bloginfo('description'),
        'Sito web: ' . home_url(),
        'Email di contatto: ' . get_option('admin_email'),
    ];

    if (function_exists('WC')) {
        $address = trim(implode(', ', array_filter([
            get_option('woocommerce_store_address'),
            get_option('woocommerce_store_city'),
            get_option('woocommerce_store_postcode'),
            get_option('woocommerce_default_country'),
        ])));
        if ($address) $lines[] = 'Indirizzo negozio: ' . $address;
    }

    return implode("\n", array_filter($lines));
}

// POST to the backend. Non-blocking by default (fire-and-forget on publish); blocking mode
// waits for the response and returns the decoded body (incl. job_id) for the realtime sync.
function wpai_backend_post($path, $payload, $blocking = false) {
    $key = wpai_opt('api_key');
    if (!$key) return null;
    $res = wp_remote_post(WPAI_BACKEND_URL . $path, [
        'timeout' => $blocking ? 20 : 15,
        'blocking' => $blocking,
        'headers' => [
            'Content-Type' => 'application/json',
            'Authorization' => 'Bearer ' . $key,
        ],
        'body' => wp_json_encode($payload),
    ]);
    if (!$blocking) return null;
    if (is_wp_error($res)) return ['error' => $res->get_error_message()];
    return json_decode(wp_remote_retrieve_body($res), true);
}

function wpai_push_content($url, $text, $blocking = false) {
    if (!trim($text)) return null;
    return wpai_backend_post('/ingest/site-page', ['url' => $url, 'text' => $text], $blocking);
}

function wpai_push_product($post, $blocking = false) {
    if (!function_exists('wc_get_product')) return null;
    $product = wc_get_product($post->ID);
    if (!$product) return null;
    return wpai_backend_post('/ingest/product', [
        'url' => get_permalink($post->ID),
        'title' => $post->post_title,
        'price' => (string) $product->get_price(),
        'image_url' => wp_get_attachment_url($product->get_image_id()) ?: '',
        'description' => wp_strip_all_tags($product->get_short_description() ?: $post->post_content),
    ], $blocking);
}

// Auto-sync on publish/update (fire-and-forget).
add_action('save_post', function ($post_id) {
    if (wp_is_post_revision($post_id) || wp_is_post_autosave($post_id)) return;

    $post = get_post($post_id);
    if (!$post || $post->post_status !== 'publish') return;
    if (!in_array($post->post_type, ['post', 'page', 'product'], true)) return;

    wpai_push_content(get_permalink($post_id), wpai_build_post_content($post));
    if ($post->post_type === 'product') wpai_push_product($post);
}, 20, 1);

// ---- AJAX: realtime item-by-item sync (drives the Sincronizzazione page) ----

function wpai_sync_check() {
    if (!current_user_can('manage_options')) wp_send_json_error('forbidden', 403);
    check_ajax_referer('wpai_sync');
}

// Return the list of items to sync (site-info + published posts/pages/products).
add_action('wp_ajax_wpai_sync_list', function () {
    wpai_sync_check();
    $items = [['type' => 'site-info', 'id' => 0, 'title' => 'Informazioni del sito']];

    $post_types = ['post', 'page'];
    if (function_exists('WC')) $post_types[] = 'product';
    $posts = get_posts(['post_type' => $post_types, 'post_status' => 'publish', 'numberposts' => -1]);
    foreach ($posts as $post) {
        $items[] = ['type' => $post->post_type, 'id' => $post->ID, 'title' => $post->post_title ?: '(senza titolo)'];
    }
    wp_send_json_success($items);
});

// Push one item to the backend (blocking) and return its ingest job_id.
add_action('wp_ajax_wpai_sync_item', function () {
    wpai_sync_check();
    // Nonce and capability are verified by wpai_sync_check() immediately above.
    // phpcs:ignore WordPress.Security.NonceVerification.Missing
    $type = sanitize_text_field(wp_unslash($_POST['type'] ?? ''));
    // phpcs:ignore WordPress.Security.NonceVerification.Missing
    $id = absint(wp_unslash($_POST['id'] ?? 0));

    if ($type === 'site-info') {
        $res = wpai_push_content(home_url() . '/#site-info', wpai_build_site_info_content(), true);
    } else {
        $post = get_post($id);
        if (!$post) wp_send_json_error('post not found', 404);
        if ($type === 'product') {
            $res = wpai_push_product($post, true);                                    // tracked job = product card
            wpai_push_content(get_permalink($id), wpai_build_post_content($post));     // + RAG text (fire-and-forget)
        } else {
            $res = wpai_push_content(get_permalink($id), wpai_build_post_content($post), true);
        }
    }
    if (!is_array($res) || empty($res['job_id'])) {
        wp_send_json_error($res['error'] ?? 'ingest failed', 502);
    }
    wp_send_json_success(['job_id' => (int) $res['job_id'], 'status' => $res['status'] ?? 'queued']);
});

// Proxy the backend job status (queued | processing | done | error).
add_action('wp_ajax_wpai_job_status', function () {
    wpai_sync_check();
    // Nonce and capability are verified by wpai_sync_check() immediately above.
    // phpcs:ignore WordPress.Security.NonceVerification.Missing
    $job_id = absint(wp_unslash($_POST['job_id'] ?? 0));
    $key = wpai_opt('api_key');
    if (!$job_id || !$key) wp_send_json_error('bad request', 400);
    $res = wp_remote_get(WPAI_BACKEND_URL . '/ingest/jobs/' . $job_id, [
        'timeout' => 8,
        'headers' => ['Authorization' => 'Bearer ' . $key],
    ]);
    if (is_wp_error($res) || wp_remote_retrieve_response_code($res) !== 200) {
        wp_send_json_error('status unavailable', 502);
    }
    wp_send_json_success(json_decode(wp_remote_retrieve_body($res), true));
});

// ---- Order lookup (chat "where's my order" feature) ----
//
// The backend calls back into this REST route (auth: the client's own api_key as a shared
// secret, same key already used for /chat) to fetch WooCommerce order data. Two tiers:
//  - anonymous but verified (order number + billing email/surname match): status + shipping
//    date only.
//  - logged-in (a short-lived signed user_token, see wpai_user_token below): full order data,
//    but only if the token's user actually owns the order.
add_action('rest_api_init', function () {
    register_rest_route('wpai/v1', '/order-lookup', [
        'methods' => 'POST',
        'permission_callback' => '__return_true', // auth is the api_key check inside the handler
        'callback' => 'wpai_order_lookup',
    ]);
});

// Server-side-only secret for signing user identity tokens. MUST NOT be the api_key: the
// api_key is public (localized into the widget JS), so signing with it would let anyone forge
// a token for any user_id and read full order data. wp_salt() never leaves the server.
function wpai_token_secret() {
    return wp_salt('auth');
}

function wpai_verify_user_token($token) {
    $parts = explode('.', (string) $token, 2);
    if (count($parts) !== 2) return null;
    [$payload_b64, $sig] = $parts;
    if (!hash_equals(hash_hmac('sha256', $payload_b64, wpai_token_secret()), $sig)) return null;
    $payload = json_decode(base64_decode($payload_b64), true);
    if (!is_array($payload) || empty($payload['exp']) || time() > $payload['exp']) return null;
    return $payload; // {user_id, email, exp}
}

function wpai_order_lookup(WP_REST_Request $req) {
    if (!function_exists('wc_get_order')) return new WP_Error('no_woocommerce', 'WooCommerce not active', ['status' => 404]);
    $key = wpai_opt('api_key');
    $auth = $req->get_header('authorization');
    if (!$key || $auth !== 'Bearer ' . $key) return new WP_Error('unauthorized', 'invalid api key', ['status' => 401]);

    $order_number = sanitize_text_field($req->get_param('order_number'));
    $order_id = (int) preg_replace('/\D/', '', $order_number);
    $order = $order_id ? wc_get_order($order_id) : false;
    if (!$order) return new WP_Error('not_found', 'order not found', ['status' => 404]);

    $token_payload = wpai_verify_user_token($req->get_param('user_token'));
    if ($token_payload) {
        $owns = $order->get_customer_id() && (int) $order->get_customer_id() === (int) $token_payload['user_id'];
        if ($owns) {
            return [
                'verified' => 'full',
                'status' => wc_get_order_status_name($order->get_status()),
                'shipping_date' => $order->get_date_completed() ? $order->get_date_completed()->date('Y-m-d') : null,
                'total' => wp_strip_all_tags($order->get_formatted_order_total()),
                'items' => array_values(array_map(fn($i) => $i->get_name() . ' x' . $i->get_quantity(), $order->get_items())),
                'shipping_address' => $order->get_formatted_shipping_address() ?: $order->get_formatted_billing_address(),
            ];
        }
    }

    // anonymous path: identifier must match the order's billing email or surname
    $identifier = trim((string) $req->get_param('identifier'));
    $matches = $identifier && (
        strcasecmp($identifier, $order->get_billing_email()) === 0 ||
        strcasecmp($identifier, $order->get_billing_last_name()) === 0
    );
    if (!$matches) return new WP_Error('verification_failed', 'order number and identifier do not match', ['status' => 403]);

    return [
        'verified' => 'basic',
        'status' => wc_get_order_status_name($order->get_status()),
        'shipping_date' => $order->get_date_completed() ? $order->get_date_completed()->date('Y-m-d') : null,
    ];
}

// Short-lived signed token proving "this visitor is logged-in WP user X" — issued only to
// logged-in users (wp_ajax_ without _nopriv_ 400s for anonymous automatically). The widget
// attaches it to /chat so the model can offer full order data instead of the basic tier.
add_action('wp_ajax_wpai_user_token', function () {
    $key = wpai_opt('api_key');
    $user = wp_get_current_user();
    if (!$key || !$user->ID) wp_send_json_error('unauthorized', 401);
    $payload = base64_encode(wp_json_encode([
        'user_id' => $user->ID,
        'email' => $user->user_email,
        'exp' => time() + 300,
    ]));
    $sig = hash_hmac('sha256', $payload, wpai_token_secret());
    wp_send_json_success(['token' => $payload . '.' . $sig]);
});
