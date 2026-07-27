<?php
/**
 * Plugin Name: WP AIssistant
 * Description: Floating AI chat widget backed by a RAG backend, with automatic site content sync.
 * Version: 0.9.0
 */

if (!defined('ABSPATH')) exit;

define('WPAI_OPTION', 'wpai_settings');
define('WPAI_VERSION', '0.9.0'); // keep in sync with the "Version:" header above

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

// ---- Admin menu: top-level "AI Assistant" with Impostazioni + Sincronizzazione ----

add_action('admin_menu', function () {
    add_menu_page('AI Assistant', 'AI Assistant', 'manage_options', 'wp-aissistant', 'wpai_settings_page', 'dashicons-format-chat', 58);
    add_submenu_page('wp-aissistant', 'Impostazioni', 'Impostazioni', 'manage_options', 'wp-aissistant', 'wpai_settings_page');
    add_submenu_page('wp-aissistant', 'Sincronizzazione', 'Sincronizzazione', 'manage_options', 'wp-aissistant-sync', 'wpai_sync_page');
});

add_action('admin_init', function () {
    register_setting('wpai', WPAI_OPTION);
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
    ?>
    <div class="wrap">
        <h1>AI Assistant — Impostazioni</h1>

        <?php if ($usage) : ?>
            <div class="wpai-admin-card">
                <h2>Piano — <?php echo esc_html($usage['plan'] ?: '—'); ?></h2>
                <?php if (!empty($usage['limit'])) : $pct = min(100, round($usage['used'] / $usage['limit'] * 100)); ?>
                    <p><strong><?php echo (int) $usage['used']; ?></strong> / <?php echo (int) $usage['limit']; ?> messaggi questo mese
                       <span style="color:#666;">(<?php echo (int) $usage['remaining']; ?> rimanenti)</span></p>
                    <div class="wpai-bar"><div class="wpai-bar-fill" style="width:<?php echo $pct; ?>%;<?php echo $pct >= 100 ? 'background:#d97706;' : ''; ?>"></div></div>
                <?php else : ?>
                    <p><strong><?php echo (int) $usage['used']; ?></strong> messaggi questo mese (nessun limite)</p>
                <?php endif; ?>
            </div>
        <?php elseif (wpai_opt('api_key')) : ?>
            <div class="wpai-admin-card"><p>Impossibile recuperare il piano dal backend. Verifica l'API Key.</p></div>
        <?php endif; ?>

        <form method="post" action="options.php">
            <?php settings_fields('wpai'); ?>
            <table class="form-table">
                <tr>
                    <th><label for="api_key">API Key</label></th>
                    <td><input type="text" id="api_key" name="<?php echo WPAI_OPTION; ?>[api_key]"
                               value="<?php echo esc_attr($opts['api_key'] ?? ''); ?>" class="regular-text" />
                        <p class="description">La trovi nel pannello operatore → Profilo.</p></td>
                </tr>
                <tr>
                    <th><label for="widget_title">Titolo widget</label></th>
                    <td><input type="text" id="widget_title" name="<?php echo WPAI_OPTION; ?>[widget_title]"
                               value="<?php echo esc_attr($opts['widget_title'] ?? ''); ?>" class="regular-text" placeholder="AI Assistant" /></td>
                </tr>
                <tr>
                    <th><label for="widget_privacy_url">URL Privacy Policy</label></th>
                    <td><input type="url" id="widget_privacy_url" name="<?php echo WPAI_OPTION; ?>[widget_privacy_url]"
                               value="<?php echo esc_attr($opts['widget_privacy_url'] ?? ''); ?>" class="regular-text" placeholder="https://tuosito.it/privacy" />
                        <p class="description">Se impostato, il widget mostra un avviso "Continuando accetti la privacy policy" con il link (GDPR).</p></td>
                </tr>
                <tr>
                    <th><label for="widget_image">Immagine widget</label></th>
                    <td>
                        <img id="wpai-image-preview" src="<?php echo esc_url($image); ?>" style="max-width:60px;max-height:60px;display:<?php echo $image ? 'block' : 'none'; ?>;margin-bottom:8px;" />
                        <input type="hidden" id="widget_image" name="<?php echo WPAI_OPTION; ?>[widget_image]" value="<?php echo esc_attr($image); ?>" />
                        <button type="button" class="button" id="wpai-image-select">Scegli immagine</button>
                        <button type="button" class="button" id="wpai-image-clear" style="display:<?php echo $image ? 'inline-block' : 'none'; ?>;">Rimuovi</button>
                    </td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
    </div>
    <script>
    jQuery(function ($) {
        var frame;
        $('#wpai-image-select').on('click', function (e) {
            e.preventDefault();
            if (frame) { frame.open(); return; }
            frame = wp.media({ title: 'Scegli immagine widget', multiple: false });
            frame.on('select', function () {
                var attachment = frame.state().get('selection').first().toJSON();
                $('#widget_image').val(attachment.url);
                $('#wpai-image-preview').attr('src', attachment.url).show();
                $('#wpai-image-clear').show();
            });
            frame.open();
        });
        $('#wpai-image-clear').on('click', function (e) {
            e.preventDefault();
            $('#widget_image').val('');
            $('#wpai-image-preview').hide();
            $(this).hide();
        });
    });
    </script>
    <?php
}

function wpai_sync_page() {
    ?>
    <div class="wrap">
        <h1>AI Assistant — Sincronizzazione</h1>
        <p>Invia al backend i contenuti del sito (pagine, articoli<?php echo function_exists('WC') ? ', prodotti' : ''; ?>) e le informazioni generali. I nuovi contenuti vengono comunque sincronizzati in automatico alla pubblicazione; usa questo per il primo caricamento o un re-sync completo.</p>
        <?php if (!wpai_opt('api_key')) : ?>
            <div class="wpai-admin-card"><p>Imposta prima l'<strong>API Key</strong> in Impostazioni.</p></div>
        <?php else : ?>
            <p><button class="button button-primary" id="wpai-sync-start">Sincronizza ora</button>
               <span id="wpai-sync-progress" style="margin-left:12px;color:#666;"></span></p>
            <div id="wpai-sync-list" class="wpai-sync-list"></div>
        <?php endif; ?>
    </div>
    <?php
}

add_action('admin_enqueue_scripts', function ($hook) {
    // settings page needs the media picker
    if ($hook === 'toplevel_page_wp-aissistant') {
        wp_enqueue_media();
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
        wp_register_style('wpai-admin', false);
        wp_enqueue_style('wpai-admin');
        wp_add_inline_style('wpai-admin', '
            .wpai-admin-card{background:#fff;border:1px solid #dcdcde;border-radius:6px;padding:14px 16px;margin:14px 0;max-width:640px;}
            .wpai-bar{height:8px;background:#f0f0f1;border-radius:999px;overflow:hidden;max-width:420px;}
            .wpai-bar-fill{height:100%;background:#2271b1;}
            .wpai-sync-list{margin-top:14px;max-width:640px;}
            .wpai-sync-row{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 12px;border:1px solid #e0e0e0;border-radius:6px;margin-bottom:6px;background:#fff;font-size:13px;}
            .wpai-sync-row .status{font-size:12px;color:#666;white-space:nowrap;}
            .wpai-sync-row.done{border-color:#c6e6c6;}
            .wpai-sync-row.done .status{color:#1e7e34;}
            .wpai-sync-row.error{border-color:#f0c0c0;}
            .wpai-sync-row.error .status{color:#b32d2e;}
        ');
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
        'loggedIn' => is_user_logged_in(),
        'privacyUrl' => wpai_opt('widget_privacy_url'),
        // The Origin/Referer header the backend would otherwise fall back to never carries a
        // path, so a subdirectory install (e.g. example.com/shop/) would build a wrong
        // order-lookup callback URL. Send the real site URL explicitly instead.
        'siteUrl' => home_url(),
    ]);
});

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
    $type = sanitize_text_field($_POST['type'] ?? '');
    $id = (int) ($_POST['id'] ?? 0);

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
    $job_id = (int) ($_REQUEST['job_id'] ?? 0);
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

function wpai_verify_user_token($token) {
    $key = wpai_opt('api_key');
    $parts = explode('.', (string) $token, 2);
    if (!$key || count($parts) !== 2) return null;
    [$payload_b64, $sig] = $parts;
    if (!hash_equals(hash_hmac('sha256', $payload_b64, $key), $sig)) return null;
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
    $sig = hash_hmac('sha256', $payload, $key);
    wp_send_json_success(['token' => $payload . '.' . $sig]);
});
