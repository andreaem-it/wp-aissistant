<?php
/**
 * Plugin Name: WP AIssistant
 * Description: Floating AI chat widget backed by a RAG backend, with automatic site content sync.
 * Version: 0.1.0
 */

if (!defined('ABSPATH')) exit;

define('WPAI_OPTION', 'wpai_settings');

// ---- Settings ----

add_action('admin_menu', function () {
    add_options_page('WP AIssistant', 'WP AIssistant', 'manage_options', 'wp-aissistant', 'wpai_settings_page');
});

add_action('admin_init', function () {
    register_setting('wpai', WPAI_OPTION);
});

function wpai_settings_page() {
    $opts = get_option(WPAI_OPTION, []);
    $image = $opts['widget_image'] ?? '';
    ?>
    <div class="wrap">
        <h1>WP AIssistant</h1>
        <form method="post" action="options.php">
            <?php settings_fields('wpai'); ?>
            <table class="form-table">
                <tr>
                    <th><label for="backend_url">Backend URL</label></th>
                    <td><input type="url" id="backend_url" name="<?php echo WPAI_OPTION; ?>[backend_url]"
                               value="<?php echo esc_attr($opts['backend_url'] ?? ''); ?>" class="regular-text" placeholder="https://api.tuodominio.com" /></td>
                </tr>
                <tr>
                    <th><label for="api_key">API Key</label></th>
                    <td><input type="text" id="api_key" name="<?php echo WPAI_OPTION; ?>[api_key]"
                               value="<?php echo esc_attr($opts['api_key'] ?? ''); ?>" class="regular-text" /></td>
                </tr>
                <tr>
                    <th><label for="widget_title">Titolo widget</label></th>
                    <td><input type="text" id="widget_title" name="<?php echo WPAI_OPTION; ?>[widget_title]"
                               value="<?php echo esc_attr($opts['widget_title'] ?? ''); ?>" class="regular-text" placeholder="AI Assistant" /></td>
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

        <hr />
        <h2>Sincronizzazione contenuti</h2>
        <p>Invia al backend tutti i contenuti pubblicati (pagine, articoli<?php echo function_exists('WC') ? ', prodotti' : ''; ?>) e le informazioni generali del sito (nome, contatti<?php echo function_exists('WC') ? ', indirizzo negozio' : ''; ?>). I nuovi contenuti vengono comunque sincronizzati automaticamente alla pubblicazione: usa questo pulsante per il primo caricamento o per un re-sync completo.</p>
        <?php if (isset($_GET['synced'])) : ?>
            <p><strong><?php echo (int) $_GET['synced']; ?> elementi inviati al backend.</strong> L'elaborazione (embedding) avviene in background sul server.</p>
        <?php endif; ?>
        <form method="post" action="<?php echo admin_url('admin-post.php'); ?>">
            <input type="hidden" name="action" value="wpai_sync_now" />
            <?php wp_nonce_field('wpai_sync_now'); ?>
            <?php submit_button('Sincronizza ora', 'secondary'); ?>
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

add_action('admin_enqueue_scripts', function ($hook) {
    if ($hook === 'settings_page_wp-aissistant') wp_enqueue_media();
});

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

// ---- Floating chat widget ----

add_action('wp_enqueue_scripts', function () {
    if (!wpai_opt('backend_url') || !wpai_opt('api_key')) return;
    wp_enqueue_style('wpai-chat', plugins_url('assets/chat-widget.css', __FILE__), [], '0.1.0');
    wp_enqueue_script('wpai-chat', plugins_url('assets/chat-widget.js', __FILE__), [], '0.1.0', true);
    wp_localize_script('wpai-chat', 'WPAI', [
        'backendUrl' => rtrim(wpai_opt('backend_url'), '/'),
        'apiKey' => wpai_opt('api_key'),
        'title' => wpai_widget_title(),
        'image' => wpai_widget_image(),
    ]);
});

// ---- Content sync: push page/post/product content and general site info to the backend ----

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

function wpai_push_content($url, $text) {
    if (!wpai_opt('backend_url') || !wpai_opt('api_key') || !trim($text)) return;
    $endpoint = add_query_arg('api_key', wpai_opt('api_key'), wpai_opt('backend_url') . '/ingest/site-page');
    return wp_remote_post($endpoint, [
        'timeout' => 15,
        'blocking' => false,
        'headers' => ['Content-Type' => 'application/json'],
        'body' => wp_json_encode(['url' => $url, 'text' => $text]),
    ]);
}

function wpai_push_product($post) {
    if (!wpai_opt('backend_url') || !wpai_opt('api_key') || !function_exists('wc_get_product')) return;
    $product = wc_get_product($post->ID);
    if (!$product) return;

    $endpoint = add_query_arg('api_key', wpai_opt('api_key'), wpai_opt('backend_url') . '/ingest/product');
    wp_remote_post($endpoint, [
        'timeout' => 15,
        'blocking' => false,
        'headers' => ['Content-Type' => 'application/json'],
        'body' => wp_json_encode([
            'url' => get_permalink($post->ID),
            'title' => $post->post_title,
            'price' => (string) $product->get_price(),
            'image_url' => wp_get_attachment_url($product->get_image_id()) ?: '',
            'description' => wp_strip_all_tags($product->get_short_description() ?: $post->post_content),
        ]),
    ]);
}

add_action('save_post', function ($post_id) {
    if (wp_is_post_revision($post_id) || wp_is_post_autosave($post_id)) return;

    $post = get_post($post_id);
    if (!$post || $post->post_status !== 'publish') return;
    if (!in_array($post->post_type, ['post', 'page', 'product'], true)) return;

    wpai_push_content(get_permalink($post_id), wpai_build_post_content($post));
    if ($post->post_type === 'product') wpai_push_product($post);
}, 20, 1);

// ---- Bulk sync: pushes all existing published content, for initial setup or re-sync ----

add_action('admin_post_wpai_sync_now', function () {
    if (!current_user_can('manage_options')) wp_die('forbidden', 403);
    check_admin_referer('wpai_sync_now');

    $count = 0;
    wpai_push_content(home_url() . '/#site-info', wpai_build_site_info_content());
    $count++;

    $post_types = ['post', 'page'];
    if (function_exists('WC')) $post_types[] = 'product';

    $posts = get_posts([
        'post_type' => $post_types,
        'post_status' => 'publish',
        'numberposts' => -1,
    ]);
    foreach ($posts as $post) {
        wpai_push_content(get_permalink($post->ID), wpai_build_post_content($post));
        if ($post->post_type === 'product') wpai_push_product($post);
        $count++;
    }

    wp_redirect(add_query_arg(['page' => 'wp-aissistant', 'synced' => $count], admin_url('options-general.php')));
    exit;
});
