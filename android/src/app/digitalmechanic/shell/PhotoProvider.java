package app.digitalmechanic.shell;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;
import java.util.regex.Pattern;

/**
 * Снимки с камеры: программа камеры пишет фото в файл приложения, сайт получает его как вложение.
 * Это урезанный FileProvider из androidx: сборка идёт без Gradle и без библиотек.
 * Отдаёт только файлы из папки кэша photos, по адресу content://app.digitalmechanic.shell.photos/имя.jpg
 */
public class PhotoProvider extends ContentProvider {

    static final String AUTHORITY = "app.digitalmechanic.shell.photos";
    private static final String DIR = "photos";
    private static final Pattern NAME = Pattern.compile("[A-Za-z0-9_-]{1,64}\\.jpg");
    /** Снимки старше суток уже ушли на сервер или не нужны */
    private static final long KEEP_MS = 24L * 60 * 60 * 1000;

    /** Новый пустой файл для снимка */
    static File newPhoto(Context context) {
        File dir = new File(context.getCacheDir(), DIR);
        if (!dir.isDirectory()) dir.mkdirs();
        File[] old = dir.listFiles();
        if (old != null) {
            long now = System.currentTimeMillis();
            for (File f : old) if (now - f.lastModified() > KEEP_MS) f.delete();
        }
        return new File(dir, "photo-" + System.currentTimeMillis() + ".jpg");
    }

    static Uri uriFor(File file) {
        return new Uri.Builder().scheme("content").authority(AUTHORITY).appendPath(file.getName()).build();
    }

    private File fileFor(Uri uri) throws FileNotFoundException {
        String name = uri.getLastPathSegment();
        if (name == null || uri.getPathSegments().size() != 1 || !NAME.matcher(name).matches()) {
            throw new FileNotFoundException("нет такого снимка: " + uri);
        }
        return new File(new File(getContext().getCacheDir(), DIR), name);
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public String getType(Uri uri) {
        return "image/jpeg";
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        return ParcelFileDescriptor.open(fileFor(uri), ParcelFileDescriptor.parseMode(mode));
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) {
        File file;
        try {
            file = fileFor(uri);
        } catch (FileNotFoundException e) {
            return null;
        }
        String[] cols = projection != null ? projection : new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        Object[] row = new Object[cols.length];
        for (int i = 0; i < cols.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(cols[i])) row[i] = file.getName();
            else if (OpenableColumns.SIZE.equals(cols[i])) row[i] = file.length();
        }
        MatrixCursor cursor = new MatrixCursor(cols, 1);
        cursor.addRow(row);
        return cursor;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException();
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException();
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        try {
            return fileFor(uri).delete() ? 1 : 0;
        } catch (FileNotFoundException e) {
            return 0;
        }
    }
}
