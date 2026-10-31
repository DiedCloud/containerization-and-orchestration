package main

import (
	"fmt"
	"log"
	"net/http"
	"runtime"
	"strconv"
	"sync"
	"time"
)

var (
	mu     sync.Mutex
	memory [][]byte
)

func health(w http.ResponseWriter, r *http.Request) { fmt.Fprintln(w, "ok") }
func eat(w http.ResponseWriter, r *http.Request) {
	mb, err := strconv.Atoi(r.URL.Query().Get("mb"))
	if err != nil || mb <= 0 || mb > 4096 {
		http.Error(w, "mb must be between 1 and 4096", 400)
		return
	}
	data := make([]byte, mb*1024*1024)
	for i := 0; i < len(data); i += 4096 {
		data[i] = 1
	}
	mu.Lock()
	memory = append(memory, data)
	mu.Unlock()
	fmt.Fprintf(w, "allocated %d MB\n", mb)
}
func burn(w http.ResponseWriter, r *http.Request) {
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		for {
		}
	}()
	fmt.Fprintln(w, "CPU burn started")
}
func main() {
	http.HandleFunc("/health", health)
	http.HandleFunc("/eat", eat)
	http.HandleFunc("/burn", burn)
	server := &http.Server{Addr: ":8080", ReadHeaderTimeout: 5 * time.Second}
	log.Println("API listening on :8080")
	log.Fatal(server.ListenAndServe())
}
