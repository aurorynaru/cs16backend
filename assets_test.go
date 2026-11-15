package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// A slow download must outlive the server-wide WriteTimeout (BLD-025): on a
// shared office line the real bundle can take longer than 120 seconds.
func TestSlowGameAssetDownloadOutlivesServerWriteTimeout(t *testing.T) {
	dir := t.TempDir()
	public := filepath.Join(dir, "public")
	if err := os.Mkdir(public, 0700); err != nil {
		t.Fatal(err)
	}
	bundle := bytes.Repeat([]byte("FX_CS16"), 1<<20) // About 7 MB, more than socket buffers hold.
	if err := os.WriteFile(filepath.Join(public, "gamefiles.zip"), bundle, 0600); err != nil {
		t.Fatal(err)
	}
	g := newGateway(context.Background(), config{adminToken: testAdminToken, maxPlayers: "2", gameDir: dir}, nil)
	server := httptest.NewUnstartedServer(g.handler())
	server.Config.WriteTimeout = 100 * time.Millisecond // Stands in for the production 120 s.
	server.Start()
	defer server.Close()

	request, _ := http.NewRequest("GET", server.URL+"/cs16/gamefiles.zip", nil)
	request.Header.Set("Authorization", "Bearer "+testAdminToken)
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	received, chunk := 0, make([]byte, 256<<10)
	for {
		time.Sleep(20 * time.Millisecond) // About 30 reads: well past the 100 ms timeout.
		n, err := response.Body.Read(chunk)
		received += n
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("download cut off after %d of %d bytes: %v", received, len(bundle), err)
		}
	}
	if received != len(bundle) {
		t.Fatalf("download cut off after %d of %d bytes", received, len(bundle))
	}
}

func TestGameAssetCacheInvalidatesSameLengthUpdate(t *testing.T) {
	dir := t.TempDir()
	public := filepath.Join(dir, "public")
	if err := os.Mkdir(public, 0700); err != nil {
		t.Fatal(err)
	}
	writeBundle := func(body string) string {
		t.Helper()
		digest := fmt.Sprintf("%x", sha256.Sum256([]byte(body)))
		if err := os.WriteFile(filepath.Join(public, "gamefiles.zip"), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(public, "gamefiles.sha256"), []byte(digest+"\n"), 0600); err != nil {
			t.Fatal(err)
		}
		return `"` + digest + `"`
	}
	g := newGateway(context.Background(), config{adminToken: testAdminToken, maxPlayers: "2", gameDir: dir}, nil)
	handler := g.handler()
	request := func(method, etag, byteRange string, authorize bool) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest(method, "/cs16/gamefiles.zip", nil)
		if authorize {
			r.Header.Set("Authorization", "Bearer "+testAdminToken)
		}
		r.Header.Set("If-None-Match", etag)
		r.Header.Set("Range", byteRange)
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w
	}
	first := writeBundle("ABCD")
	if response := request("HEAD", "", "", false); response.Code != http.StatusUnauthorized || response.Header().Get("ETag") != "" {
		t.Fatal("unauthenticated request accessed asset metadata")
	}
	head := request("HEAD", "", "", true)
	if head.Code != 200 || head.Header().Get("ETag") != first || head.Header().Get("Content-Length") != "4" || head.Body.Len() != 0 {
		t.Fatal("authenticated HEAD did not expose current bundle identity")
	}
	partial := request("GET", "", "bytes=1-2", true)
	if partial.Code != 206 || partial.Body.String() != "BC" || partial.Header().Get("ETag") != first {
		t.Fatal("range request did not preserve asset bytes and identity")
	}
	if cached := request("GET", first, "", true); cached.Code != 304 || cached.Body.Len() != 0 {
		t.Fatal("current asset validator was not honored")
	}
	second := writeBundle("WXYZ") // Same size as the old bundle.
	changed := request("GET", first, "", true)
	if changed.Code != 200 || changed.Body.String() != "WXYZ" || changed.Header().Get("ETag") != second || first == second {
		t.Fatal("equal-length changed asset remained cached under its old identity")
	}
}
