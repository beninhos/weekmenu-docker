// ah-login-proxy: reverse proxy naar login.ah.nl op een vaste poort.
// Gebaseerd op de login-implementatie van appie-go (github.com/gwillem/appie-go).
// Herschrijft appie://login-exit naar /callback, wisselt de OAuth-code in
// voor tokens en schrijft ze naar /tmp/appie-tokens.json.
package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"
)

const (
	loginBase  = "https://login.ah.nl"
	tokenURL   = "https://api.ah.nl/mobile-auth/v1/auth/token"
	clientID   = "appie-ios"
	listenAddr = "0.0.0.0:9002"
	tokenFile  = "/tmp/appie-tokens.json"
)

var localOrigin = "http://localhost:9002"

var successPage = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Gekoppeld!</title>
<style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;
height:100vh;margin:0;background:#f0fdf4;}
.card{background:white;border-radius:12px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1);}
h1{color:#16a34a;margin:0 0 12px;}p{color:#6b7280;margin:0;}</style></head>
<body><div class="card"><h1>✓ Gekoppeld!</h1>
<p>Je AH-account is succesvol gekoppeld.<br>Je kunt dit tabblad sluiten.</p></div></body></html>`

var errorPage = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Fout</title>
<style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;
height:100vh;margin:0;background:#fef2f2;}
.card{background:white;border-radius:12px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1);}
h1{color:#dc2626;margin:0 0 12px;}p{color:#6b7280;margin:0;}</style></head>
<body><div class="card"><h1>✗ Koppelen mislukt</h1>
<p>%s</p></div></body></html>`

type tokenResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
}

type savedTokens struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresAt    int64  `json:"expires_at"`
}

func exchangeCode(code string) error {
	body, _ := json.Marshal(map[string]string{
		"clientId": clientID,
		"code":     code,
	})
	req, _ := http.NewRequest("POST", tokenURL, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("token request mislukt: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("AH token endpoint: HTTP %d — %s", resp.StatusCode, string(b))
	}

	var tok tokenResponse
	if err := json.NewDecoder(resp.Body).Decode(&tok); err != nil {
		return fmt.Errorf("token response onleesbaar: %w", err)
	}

	expiresAt := time.Now().Unix() + int64(tok.ExpiresIn)
	if tok.ExpiresIn == 0 {
		expiresAt = time.Now().Unix() + 604798
	}

	out := savedTokens{
		AccessToken:  tok.AccessToken,
		RefreshToken: tok.RefreshToken,
		ExpiresAt:    expiresAt,
	}
	data, _ := json.Marshal(out)
	return os.WriteFile(tokenFile, data, 0600)
}

// readResponseBody leest de body en decomprimeert gzip indien aanwezig.
// Gebaseerd op appie-go's readResponseBody.
func readResponseBody(resp *http.Response) ([]byte, error) {
	var reader io.Reader = resp.Body
	if resp.Header.Get("Content-Encoding") == "gzip" {
		gz, err := gzip.NewReader(resp.Body)
		if err != nil {
			return nil, err
		}
		defer gz.Close()
		reader = gz
	}
	data, err := io.ReadAll(reader)
	resp.Body.Close()
	return data, err
}

// sanitizeCookie verwijdert Secure, SameSite en Domain zodat cookies werken
// over plain HTTP op localhost. Gebaseerd op appie-go's sanitizeCookie.
func sanitizeCookie(cookie string) string {
	parts := strings.Split(cookie, ";")
	out := parts[:1]
	for _, p := range parts[1:] {
		attr := strings.ToLower(strings.TrimSpace(p))
		if attr == "secure" ||
			strings.HasPrefix(attr, "samesite") ||
			strings.HasPrefix(attr, "domain") {
			continue
		}
		out = append(out, p)
	}
	return strings.Join(out, ";")
}

// rewriteLoginResponse herschrijft de response van login.ah.nl.
// Gebaseerd op appie-go's rewriteLoginResponse.
func rewriteLoginResponse(resp *http.Response) error {
	// Onderschep server-side appie:// redirects
	loc := resp.Header.Get("Location")
	if strings.HasPrefix(loc, "appie://") {
		u, err := url.Parse(loc)
		if err == nil {
			newLoc := localOrigin + "/callback?" + u.RawQuery
			resp.Header.Set("Location", newLoc)
			log.Printf("Redirect onderschept → %s", newLoc)
		}
		return nil
	}

	// Herschrijf Location headers die naar login.ah.nl verwijzen
	if strings.Contains(loc, "login.ah.nl") {
		resp.Header.Set("Location", strings.ReplaceAll(loc, "https://login.ah.nl", localOrigin))
	}

	// Verwijder beveiligingsheaders
	resp.Header.Del("Content-Security-Policy")
	resp.Header.Del("Strict-Transport-Security")
	resp.Header.Del("X-Frame-Options")

	// Saneer cookies
	if cookies := resp.Header.Values("Set-Cookie"); len(cookies) > 0 {
		resp.Header.Del("Set-Cookie")
		for _, c := range cookies {
			resp.Header.Add("Set-Cookie", sanitizeCookie(c))
		}
	}

	// Herschrijf text bodies (HTML, JS, JSON)
	ct := resp.Header.Get("Content-Type")
	if !strings.Contains(ct, "text/html") &&
		!strings.Contains(ct, "javascript") &&
		!strings.Contains(ct, "json") {
		return nil
	}

	body, err := readResponseBody(resp)
	if err != nil {
		return err
	}

	// Vervang appie://login-exit door onze callback — werkt in HTML én JS-bundles
	body = bytes.ReplaceAll(body, []byte("appie://login-exit"), []byte(localOrigin+"/callback"))
	// Vervang login.ah.nl URLs
	body = bytes.ReplaceAll(body, []byte("https://login.ah.nl"), []byte(localOrigin))

	resp.Header.Del("Content-Encoding")
	resp.Body = io.NopCloser(bytes.NewReader(body))
	resp.ContentLength = int64(len(body))
	resp.Header.Set("Content-Length", fmt.Sprintf("%d", len(body)))

	return nil
}

func buildProxy() http.Handler {
	target, _ := url.Parse(loginBase)

	return &httputil.ReverseProxy{
		Director: func(req *http.Request) {
			req.URL.Scheme = target.Scheme
			req.URL.Host = target.Host
			req.Host = target.Host
			req.Header.Del("Accept-Encoding")
			req.Header.Del("X-Forwarded-For")
			req.Header.Del("X-Real-Ip")
		},
		ModifyResponse: func(resp *http.Response) error {
			return rewriteLoginResponse(resp)
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			log.Printf("Proxy fout: %v", err)
			http.Error(w, "Proxy fout: "+err.Error(), 502)
		},
	}
}

func main() {
	proxy := buildProxy()
	mux := http.NewServeMux()

	// Callback: ontvang OAuth code, wissel in voor tokens
	mux.HandleFunc("/callback", func(w http.ResponseWriter, r *http.Request) {
		code := r.URL.Query().Get("code")
		if code == "" {
			msg := "Geen OAuth-code ontvangen"
			log.Println(msg)
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.WriteHeader(400)
			fmt.Fprintf(w, errorPage, msg)
			return
		}
		log.Printf("OAuth code ontvangen, tokens ophalen…")
		if err := exchangeCode(code); err != nil {
			log.Printf("Token exchange mislukt: %v", err)
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.WriteHeader(500)
			fmt.Fprintf(w, errorPage, err.Error())
			return
		}
		log.Println("✓ Tokens opgeslagen in", tokenFile)
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, successPage)
	})

	// Root: stuur direct naar de OAuth-pagina
	oauthPath := "/login?client_id=" + clientID + "&response_type=code&redirect_uri=appie://login-exit"
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/" {
			http.Redirect(w, r, localOrigin+oauthPath, http.StatusFound)
			return
		}
		proxy.ServeHTTP(w, r)
	})

	log.Printf("AH login proxy gestart op %s", listenAddr)
	log.Printf("Bezoek via SSH-tunnel: http://localhost:9002")
	if err := http.ListenAndServe(listenAddr, mux); err != nil {
		log.Fatalf("Server fout: %v", err)
	}
}
