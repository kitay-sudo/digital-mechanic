package app.digitalmechanic.shell;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/**
 * «Цифровой механик»: приложение-оболочка.
 * При первом запуске спрашивает адрес сервера, дальше показывает сайт системы в своём окне.
 * Сам интерфейс живёт на сервере, поэтому приложение не нужно обновлять вместе с сайтом.
 */
public class MainActivity extends Activity {

    private static final String PREFS = "dm";
    private static final String KEY_SERVER = "server";
    /** Метка в строке User-Agent: по ней сайт понимает, что открыт в приложении */
    private static final String UA_MARK = " DigitalMechanicApp/";

    private WebView web;
    private String server;
    private long lastBack;
    /** Страница хотя бы раз загрузилась: после этого сбой сети показывает сам сайт */
    private boolean loaded;
    /** Экран адреса открыт из настроек сайта: «Назад» возвращает к сайту */
    private boolean returnToSite;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        server = prefs().getString(KEY_SERVER, null);
        if (server == null) showSetup("http://", null, false);
        else openServer();
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private int dp(float value) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics()));
    }

    private int color(int id) {
        return getResources().getColor(id, getTheme());
    }

    private String version() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "0";
        }
    }

    /* ---------- Экран адреса сервера ---------- */

    private void showSetup(String address, String error, boolean fromSite) {
        returnToSite = fromSite;
        if (web != null) {
            web.stopLoading();
            web.destroy();
            web = null;
        }
        loaded = false;

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER_HORIZONTAL);
        box.setPadding(dp(24), dp(48), dp(24), dp(24));

        ImageView icon = new ImageView(this);
        icon.setImageResource(R.mipmap.ic_launcher);
        box.addView(icon, new LinearLayout.LayoutParams(dp(88), dp(88)));

        TextView title = new TextView(this);
        title.setText(R.string.setup_title);
        title.setTextColor(color(R.color.text));
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        title.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        titleLp.topMargin = dp(20);
        box.addView(title, titleLp);

        TextView text = new TextView(this);
        text.setText(R.string.setup_text);
        text.setTextColor(color(R.color.text2));
        text.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        text.setLineSpacing(dp(4), 1f);
        LinearLayout.LayoutParams textLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        textLp.topMargin = dp(12);
        box.addView(text, textLp);

        final EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setImeOptions(EditorInfo.IME_ACTION_GO);
        input.setHint(R.string.setup_hint);
        input.setText(address);
        input.setSelection(input.getText().length());
        input.setTextColor(color(R.color.text));
        input.setHintTextColor(color(R.color.text2));
        input.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        input.setPadding(dp(16), 0, dp(16), 0);
        GradientDrawable field = new GradientDrawable();
        field.setColor(color(R.color.panel));
        field.setStroke(dp(1), color(R.color.line));
        field.setCornerRadius(dp(4));
        input.setBackground(field);
        LinearLayout.LayoutParams inputLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(56));
        inputLp.topMargin = dp(24);
        box.addView(input, inputLp);

        final TextView problem = new TextView(this);
        problem.setTextColor(color(R.color.error));
        problem.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        problem.setLineSpacing(dp(3), 1f);
        if (error != null) problem.setText(error);
        else problem.setVisibility(View.GONE);
        LinearLayout.LayoutParams problemLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        problemLp.topMargin = dp(10);
        box.addView(problem, problemLp);

        Button connect = new Button(this);
        connect.setText(R.string.setup_connect);
        connect.setAllCaps(false);
        connect.setTextColor(color(R.color.accent_text));
        connect.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        GradientDrawable button = new GradientDrawable();
        button.setColor(color(R.color.accent));
        button.setCornerRadius(dp(4));
        connect.setBackground(button);
        connect.setStateListAnimator(null);
        LinearLayout.LayoutParams connectLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(56));
        connectLp.topMargin = dp(16);
        box.addView(connect, connectLp);

        TextView about = new TextView(this);
        about.setText("версия " + version());
        about.setTextColor(color(R.color.text2));
        about.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        about.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams aboutLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        aboutLp.topMargin = dp(20);
        box.addView(about, aboutLp);

        final Runnable submit = new Runnable() {
            @Override
            public void run() {
                String url = normalize(input.getText().toString());
                if (url == null) {
                    problem.setText(R.string.setup_bad_address);
                    problem.setVisibility(View.VISIBLE);
                    return;
                }
                server = url;
                prefs().edit().putString(KEY_SERVER, url).apply();
                openServer();
            }
        };
        connect.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                submit.run();
            }
        });
        input.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView v, int action, KeyEvent event) {
                if (action == EditorInfo.IME_ACTION_GO || action == EditorInfo.IME_ACTION_DONE) {
                    submit.run();
                    return true;
                }
                return false;
            }
        });

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(color(R.color.bg));
        scroll.addView(box, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(scroll);
    }

    /** Приводит введённый адрес к виду «схема://узел[:порт]». Возвращает null, если адрес не разобрать. */
    static String normalize(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) return null;
        if (!s.contains("://")) s = "http://" + s;
        Uri uri = Uri.parse(s);
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();
        String host = uri.getHost();
        if (!(scheme.equals("http") || scheme.equals("https")) || host == null || host.isEmpty()) return null;
        String out = scheme + "://" + host;
        if (uri.getPort() > 0) out += ":" + uri.getPort();
        return out;
    }

    /* ---------- Окно с сайтом ---------- */

    private void openServer() {
        loaded = false;
        web = new WebView(this);
        web.setBackgroundColor(color(R.color.bg));

        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        // Настройки механика и отметки шагов сайт хранит в хранилище браузера
        settings.setDomStorageEnabled(true);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        settings.setUserAgentString(settings.getUserAgentString() + UA_MARK + version());

        web.addJavascriptInterface(new Bridge(), "DigitalMechanicApp");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri url = request.getUrl();
                Uri home = Uri.parse(server);
                boolean own = home.getHost() != null && home.getHost().equalsIgnoreCase(url.getHost()) && home.getPort() == url.getPort();
                if (own) return false;
                // Чужие ссылки открываются в браузере телефона, а не внутри приложения
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, url));
                } catch (Exception ignored) {
                    // на телефоне нет программы для такой ссылки
                }
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                super.onPageStarted(view, url, favicon);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                loaded = true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                // Сервер не ответил при первом открытии: возвращаемся к адресу. Позже сбой сети показывает сам сайт
                if (request.isForMainFrame() && !loaded) {
                    showSetup(server, getString(R.string.setup_no_connection), false);
                }
            }
        });

        setContentView(web, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        web.loadUrl(server + "/");
    }

    /** Что сайт может попросить у приложения. Доступно в странице как window.DigitalMechanicApp */
    private final class Bridge {
        @JavascriptInterface
        public String version() {
            return MainActivity.this.version();
        }

        @JavascriptInterface
        public String server() {
            return server;
        }

        /** Сменить адрес сервера: вызывается из настроек сайта */
        @JavascriptInterface
        public void changeServer() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    showSetup(server, null, true);
                }
            });
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        // Экран адреса открыт из настроек сайта: «Назад» возвращает к сайту
        if (web == null && returnToSite && server != null) {
            returnToSite = false;
            openServer();
            return;
        }
        long now = System.currentTimeMillis();
        if (now - lastBack < 2000) {
            super.onBackPressed();
            return;
        }
        lastBack = now;
        Toast.makeText(this, R.string.exit_hint, Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
