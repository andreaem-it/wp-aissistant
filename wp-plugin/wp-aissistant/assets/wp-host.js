/**
 * L'adapter WordPress del widget.
 *
 * È l'unico posto del plugin che sa ancora come si parla con WordPress dal browser: il carrello
 * WooCommerce, il token che prova l'identità di un utente loggato, e i frammenti jQuery da
 * aggiornare dopo un'aggiunta. Il widget non conosce niente di tutto questo — riceve un oggetto
 * con tre capacità e funziona anche senza.
 *
 * Gira **prima** del bundle e attacca l'adapter alla configurazione, che il bundle legge quando
 * parte. L'ordine è garantito dalle dipendenze dichiarate in `wp_enqueue_script`.
 */
(function () {
  const cfg = window.WPAissistantConfig;
  if (!cfg || !window.WPAI_HOST) return;
  const wp = window.WPAI_HOST;

  let tokenPromise = null;

  cfg.host = {
    siteUrl: wp.siteUrl,

    /**
     * Un utente loggato può dimostrare chi è: il backend gli dà i dati completi dell'ordine
     * invece del solo stato. Il token è firmato lato server con `wp_salt()`, mai con l'api_key
     * — quella sta in ogni pagina pubblica, e firmarci un'identità la renderebbe falsificabile.
     * Restituisce `null` per un visitatore anonimo, che è il caso normale.
     */
    identityToken: wp.loggedIn
      ? function () {
          if (!tokenPromise) {
            tokenPromise = fetch(wp.ajaxUrl, {
              method: "POST",
              headers: { "Content-Type": "application/x-www-form-urlencoded" },
              body: new URLSearchParams({ action: "wpai_user_token" }),
            })
              .then((r) => r.json())
              .then((res) => (res && res.success ? res.data.token : null))
              .catch(() => null);
          }
          return tokenPromise;
        }
      : null,

    /**
     * Quante cose ci sono nel carrello, per le regole proattive che dipendono da questo.
     * Cookie standard di WooCommerce: presente e maggiore di zero quando il carrello non è vuoto.
     */
    cartItemCount: function () {
      const match = document.cookie.match(/(?:^|;\s*)woocommerce_items_in_cart=(\d+)/);
      return match ? Number(match[1]) : 0;
    },

    /**
     * Aggiunge al carrello WooCommerce.
     *
     * Restituisce `{ optionsUrl }` quando il prodotto ha varianti da scegliere — il widget
     * trasforma allora il pulsante in un collegamento alla pagina prodotto — e solleva quando
     * l'aggiunta non riesce, perché un pulsante che dice "aggiunto" senza aver aggiunto niente
     * è la conferma ottimistica che la regola 6 vieta.
     */
    addToCart: wp.cartNonce
      ? async function (product, button) {
          const response = await fetch(wp.ajaxUrl, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({
              action: "wpai_add_to_cart",
              nonce: wp.cartNonce,
              product_url: product.product_url,
            }),
          });
          const result = await response.json();
          if (!response.ok || !result.success) {
            const error = result && result.data ? result.data : {};
            if (error.product_url) return { optionsUrl: error.product_url };
            throw new Error(error.message || "Aggiunta non riuscita");
          }
          // WooCommerce aggiorna i propri frammenti (mini-carrello, contatore) ascoltando questi
          // eventi: senza, il carrello cambia davvero ma la pagina continua a mostrare il totale
          // di prima, che al visitatore sembra un'aggiunta non riuscita.
          if (window.jQuery) {
            window.jQuery(document.body).trigger("added_to_cart", [
              result.data.fragments || {},
              result.data.cart_hash || "",
              window.jQuery(button),
            ]);
            window.jQuery(document.body).trigger("wc_fragment_refresh");
          }
          document.body.dispatchEvent(new CustomEvent("wpai_cart_updated", { detail: result.data }));
          return { ok: true };
        }
      : null,
  };
})();
