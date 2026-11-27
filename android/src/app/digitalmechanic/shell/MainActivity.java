package app.digitalmechanic.shell;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.provider.Settings;
import android.text.InputType;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
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

import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * «Цифровой механик»: приложение-оболочка.
 * При первом запуске спрашивает адрес сервера, дальше показывает сайт системы в своём окне.
 * Сам интерфейс живёт на сервере, поэтому приложение не нужно обновлять вместе с сайтом.
 * Микрофон (голосовой ввод) и камеру (фото узла) сайт получает через разрешения телефона.
 */
public class MainActivity extends Activity {

    private static final String TAG = "DigitalMechanic";
    private static final String PREFS = "dm";
    private static final String KEY_SERVER = "server";
    /** Разрешения на микрофон и камеру уже спрашивали при запуске: дальше только по делу */
    private static final String KEY_ASKED = "asked_permissions";
    /** Метка в строке User-Agent: по ней сайт понимает, что открыт в приложении */
    private static final String UA_MARK = " DigitalMechanicApp/";

    private static final int REQ_START = 1;
    private static final int REQ_WEB = 2;
    private static final int REQ_CAMERA = 3;
    private static final int PICK_FILE = 10;
    private static final int TAKE_PHOTO = 11;

    private WebView web;
    private String server;
    private long lastBack;
    /** Страница хотя бы раз загрузилась: после этого сбой сети показывает сам сайт */
    private boolean loaded;
    /** Экран адреса открыт из настроек сайта: «Назад» возвращает к сайту */
    private boolean returnToSite;

    /** Сайт ждёт выбранные файлы: ответить нужно всегда, хотя бы null, иначе выбор больше не откроется */
    private ValueCallback<Uri[]> fileCallback;
    private boolean pickMultiple;
    private String[] pickTypes;
    /** Файл, в который программа камеры пишет снимок */
    private File photoFile;
    /** Запрос сайта на микрофон или камеру, ждущий ответа на разрешение телефона */
    private PermissionRequest webRequest;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        server = prefs().getString(KEY_SERVER, null);
        if (server == null) showSetup("http://", null, false);
        else openServer();
        askAtStart();
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
        dropPending();
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
                if (isOwn(url)) return false;
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
            public void onPageFinished(final WebView view, final String url) {
                loaded = true;
                // В журнал телефона (adb logcat -s DigitalMechanic): есть ли на странице микрофон
                view.evaluateJavascript(
                        "JSON.stringify({secure: window.isSecureContext,"
                                + " mediaDevices: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),"
                                + " recorder: typeof MediaRecorder !== 'undefined'})",
                        value -> Log.i(TAG, "страница " + url + " " + value));
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                // Сервер не ответил при первом открытии: возвращаемся к адресу. Позже сбой сети показывает сам сайт
                if (request.isForMainFrame() && !loaded) {
                    showSetup(server, getString(R.string.setup_no_connection), false);
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                onWebPermission(request);
            }

            @Override
            public void onPermissionRequestCanceled(PermissionRequest request) {
                if (webRequest == request) webRequest = null;
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                return showFileChooser(callback, params);
            }
        });

        setContentView(web, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        web.loadUrl(server + "/");
    }

    /** Адрес на нашем сервере (тот же узел и порт) */
    private boolean isOwn(Uri url) {
        Uri home = Uri.parse(server);
        return url != null && home.getHost() != null && home.getHost().equalsIgnoreCase(url.getHost()) && home.getPort() == url.getPort();
    }

    private void toast(int text) {
        Toast.makeText(this, text, Toast.LENGTH_LONG).show();
    }

    /* ---------- Разрешения телефона: микрофон и камера ---------- */

    private boolean granted(String permission) {
        return checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    /**
     * При первом запуске сразу спрашиваем микрофон и камеру: выдать их при установке Android не даёт.
     * Если механик отказал, спросим снова, когда он нажмёт микрофон или выберет камеру.
     */
    private void askAtStart() {
        if (prefs().getBoolean(KEY_ASKED, false)) return;
        List<String> missing = new ArrayList<>();
        for (String p : new String[] {Manifest.permission.RECORD_AUDIO, Manifest.permission.CAMERA}) {
            if (!granted(p)) missing.add(p);
        }
        prefs().edit().putBoolean(KEY_ASKED, true).apply();
        if (!missing.isEmpty()) requestPermissions(missing.toArray(new String[0]), REQ_START);
    }

    /** Разрешение телефона, без которого странице нельзя выдать этот ресурс */
    private static String systemPermission(String resource) {
        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)) return Manifest.permission.RECORD_AUDIO;
        if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)) return Manifest.permission.CAMERA;
        return null;
    }

    /** Сайт просит микрофон (getUserMedia): выдаём, если телефон разрешил, иначе сначала спрашиваем механика */
    private void onWebPermission(PermissionRequest request) {
        Log.i(TAG, "сайт просит " + Arrays.toString(request.getResources()) + " для " + request.getOrigin());
        if (!isOwn(request.getOrigin())) {
            request.deny();
            return;
        }
        List<String> need = new ArrayList<>();
        boolean known = false;
        for (String resource : request.getResources()) {
            String p = systemPermission(resource);
            if (p == null) continue;
            known = true;
            if (!granted(p) && !need.contains(p)) need.add(p);
        }
        if (!known) {
            request.deny();
            return;
        }
        if (need.isEmpty()) {
            grantWeb(request);
            return;
        }
        if (webRequest != null) webRequest.deny();
        webRequest = request;
        requestPermissions(need.toArray(new String[0]), REQ_WEB);
    }

    /** Выдать странице то, на что телефон дал разрешение; если ничего — отказ */
    private void grantWeb(PermissionRequest request) {
        List<String> ok = new ArrayList<>();
        for (String resource : request.getResources()) {
            String p = systemPermission(resource);
            if (p != null && granted(p)) ok.add(resource);
        }
        Log.i(TAG, "сайту выдано " + ok);
        if (ok.isEmpty()) {
            request.deny();
            explainDenied(Manifest.permission.RECORD_AUDIO, R.string.no_mic_permission);
        } else {
            request.grant(ok.toArray(new String[0]));
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        Log.i(TAG, "ответ на разрешения " + Arrays.toString(permissions) + " " + Arrays.toString(results));
        if (code == REQ_WEB) {
            PermissionRequest request = webRequest;
            webRequest = null;
            if (request != null && web != null) grantWeb(request);
        } else if (code == REQ_CAMERA) {
            if (fileCallback == null) return;
            if (granted(Manifest.permission.CAMERA)) {
                takePhoto();
            } else {
                finishChoice(null);
                explainDenied(Manifest.permission.CAMERA, R.string.no_camera_permission);
            }
        }
    }

    /**
     * Механик отказал. Если Android больше не покажет запрос (отказ дважды или «не спрашивать»),
     * предлагаем открыть настройки приложения, иначе просто подсказка.
     */
    private void explainDenied(String permission, int text) {
        if (shouldShowRequestPermissionRationale(permission)) {
            toast(text);
            return;
        }
        new AlertDialog.Builder(this)
                .setMessage(text)
                .setPositiveButton(R.string.open_settings, (dialog, which) -> {
                    Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.fromParts("package", getPackageName(), null));
                    try {
                        startActivity(intent);
                    } catch (ActivityNotFoundException ignored) {
                        // на телефоне нет экрана настроек приложения
                    }
                })
                .setNegativeButton(R.string.close, null)
                .show();
    }

    /* ---------- Фото к сообщению: камера или галерея ---------- */

    /** Сайт открыл выбор файла (input type=file): для картинок предлагаем камеру или галерею */
    private boolean showFileChooser(ValueCallback<Uri[]> callback, WebChromeClient.FileChooserParams params) {
        Log.i(TAG, "выбор файла: " + Arrays.toString(params.getAcceptTypes())
                + " несколько=" + (params.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE)
                + " capture=" + params.isCaptureEnabled());
        finishChoice(null); // прошлый выбор не закончился: закрываем его, иначе сайт ждал бы вечно
        fileCallback = callback;
        pickMultiple = params.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE;
        pickTypes = mimeTypes(params.getAcceptTypes());

        boolean images = true;
        for (String t : pickTypes) images &= t.startsWith("image/");
        if (!images) {
            pickFiles();
        } else if (params.isCaptureEnabled()) {
            startCamera();
        } else {
            new AlertDialog.Builder(this)
                    .setTitle(R.string.pick_title)
                    .setItems(new CharSequence[] {getString(R.string.pick_camera), getString(R.string.pick_gallery)},
                            (dialog, which) -> {
                                if (which == 0) startCamera();
                                else pickFiles();
                            })
                    .setOnCancelListener(dialog -> finishChoice(null))
                    .show();
        }
        return true;
    }

    /** accept из страницы («image/*», «.jpg») в список типов для Android */
    private static String[] mimeTypes(String[] accept) {
        List<String> out = new ArrayList<>();
        if (accept != null) {
            for (String a : accept) {
                for (String part : a.split(",")) {
                    String t = part.trim().toLowerCase();
                    if (t.startsWith(".")) t = MimeTypeMap.getSingleton().getMimeTypeFromExtension(t.substring(1));
                    if (t != null && t.contains("/") && !out.contains(t)) out.add(t);
                }
            }
        }
        if (out.isEmpty()) out.add("*/*");
        return out.toArray(new String[0]);
    }

    private void pickFiles() {
        Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType(pickTypes.length == 1 ? pickTypes[0] : "*/*");
        if (pickTypes.length > 1) intent.putExtra(Intent.EXTRA_MIME_TYPES, pickTypes);
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, pickMultiple);
        try {
            startActivityForResult(intent, PICK_FILE);
        } catch (ActivityNotFoundException e) {
            toast(R.string.no_file_app);
            finishChoice(null);
        }
    }

    /** Камера: если разрешения нет, сначала спрашиваем, иначе Android не даст открыть программу камеры */
    private void startCamera() {
        if (granted(Manifest.permission.CAMERA)) takePhoto();
        else requestPermissions(new String[] {Manifest.permission.CAMERA}, REQ_CAMERA);
    }

    private void takePhoto() {
        photoFile = PhotoProvider.newPhoto(this);
        Uri uri = PhotoProvider.uriFor(photoFile);
        Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        intent.putExtra(MediaStore.EXTRA_OUTPUT, uri);
        intent.setClipData(ClipData.newRawUri("", uri));
        intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivityForResult(intent, TAKE_PHOTO);
        } catch (ActivityNotFoundException | SecurityException e) {
            Log.w(TAG, "камера не открылась", e);
            photoFile = null;
            toast(R.string.no_camera_app);
            finishChoice(null);
        }
    }

    @Override
    protected void onActivityResult(int code, int result, Intent data) {
        if (code == TAKE_PHOTO) {
            File file = photoFile;
            photoFile = null;
            boolean ok = result == RESULT_OK && file != null && file.length() > 0;
            Log.i(TAG, "снимок: " + (ok ? file.getName() + " " + file.length() + " байт" : "отменён"));
            if (ok) {
                finishChoice(new Uri[] {PhotoProvider.uriFor(file)});
            } else {
                if (file != null) file.delete();
                finishChoice(null);
            }
        } else if (code == PICK_FILE) {
            Uri[] uris = result == RESULT_OK ? picked(data) : null;
            Log.i(TAG, "выбрано файлов: " + (uris == null ? 0 : uris.length));
            finishChoice(uris);
        } else {
            super.onActivityResult(code, result, data);
        }
    }

    private Uri[] picked(Intent data) {
        if (data == null) return null;
        List<Uri> out = new ArrayList<>();
        ClipData clip = data.getClipData();
        if (clip != null) {
            for (int i = 0; i < clip.getItemCount(); i++) {
                Uri u = clip.getItemAt(i).getUri();
                if (u != null) out.add(u);
            }
        }
        if (out.isEmpty() && data.getData() != null) out.add(data.getData());
        if (out.isEmpty()) return null;
        if (!pickMultiple) return new Uri[] {out.get(0)};
        return out.toArray(new Uri[0]);
    }

    /** Отдать сайту выбранные файлы; null — выбор отменён */
    private void finishChoice(Uri[] uris) {
        ValueCallback<Uri[]> callback = fileCallback;
        fileCallback = null;
        if (callback != null) callback.onReceiveValue(uris);
    }

    /** Окно сайта закрывается: незаконченные запросы страницы закрываем */
    private void dropPending() {
        if (webRequest != null) {
            webRequest.deny();
            webRequest = null;
        }
        finishChoice(null);
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
        dropPending();
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
