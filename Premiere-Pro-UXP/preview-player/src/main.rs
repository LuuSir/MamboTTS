#![windows_subsystem = "windows"]

use rodio::{Decoder, DeviceSinkBuilder, Player};
use std::fs::File;
use std::io::{ErrorKind, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;
use std::time::{Duration, Instant};

const LISTEN_ADDRESS: &str = "127.0.0.1:39881";
const MAX_REQUEST_BYTES: usize = 16 * 1024;

fn main() {
    let listener = match TcpListener::bind(LISTEN_ADDRESS) {
        Ok(listener) => listener,
        Err(_) => return,
    };
    if listener.set_nonblocking(true).is_err() {
        return;
    }

    let output = match DeviceSinkBuilder::open_default_sink() {
        Ok(output) => output,
        Err(_) => return,
    };
    let player = Player::connect_new(output.mixer());
    let mut idle_since = Instant::now();

    while idle_since.elapsed() < Duration::from_secs(30 * 60) {
        match listener.accept() {
            Ok((stream, _)) => {
                handle_request(stream, &player);
                idle_since = Instant::now();
            }
            Err(error) if error.kind() == ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(25));
            }
            Err(_) => break,
        }
    }
    player.stop();
}

fn handle_request(mut stream: TcpStream, player: &Player) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let request = match read_request(&mut stream) {
        Ok(request) => request,
        Err(message) => {
            write_response(&mut stream, 400, &message);
            return;
        }
    };

    if request.method == "OPTIONS" {
        write_response(&mut stream, 204, "");
        return;
    }
    if request.method == "GET" && request.path == "/health" {
        write_response(&mut stream, 200, "ok");
        return;
    }
    if request.method == "POST" && request.path == "/stop" {
        player.stop();
        write_response(&mut stream, 200, "ok");
        return;
    }
    if request.method == "POST" && request.path == "/play" {
        player.stop();
        let path = match String::from_utf8(request.body) {
            Ok(path) if !path.is_empty() => path,
            _ => {
                write_response(&mut stream, 400, "invalid audio path");
                return;
            }
        };
        let file = match File::open(path) {
            Ok(file) => file,
            Err(error) => {
                write_response(&mut stream, 404, &error.to_string());
                return;
            }
        };
        let decoder = match Decoder::try_from(file) {
            Ok(decoder) => decoder,
            Err(error) => {
                write_response(&mut stream, 422, &error.to_string());
                return;
            }
        };
        player.append(decoder);
        player.play();
        write_response(&mut stream, 200, "ok");
        return;
    }

    write_response(&mut stream, 404, "not found");
}

struct Request {
    method: String,
    path: String,
    body: Vec<u8>,
}

fn read_request(stream: &mut TcpStream) -> Result<Request, String> {
    let mut data = Vec::new();
    let mut buffer = [0_u8; 4096];
    let (header_end, content_length) = loop {
        let read = stream.read(&mut buffer).map_err(|error| error.to_string())?;
        if read == 0 {
            return Err("incomplete request".to_string());
        }
        data.extend_from_slice(&buffer[..read]);
        if data.len() > MAX_REQUEST_BYTES {
            return Err("request too large".to_string());
        }
        if let Some(header_end) = find_bytes(&data, b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&data[..header_end]);
            let content_length = parse_content_length(&headers)?;
            break (header_end, content_length);
        }
    };

    let body_start = header_end + 4;
    while data.len() < body_start + content_length {
        let read = stream.read(&mut buffer).map_err(|error| error.to_string())?;
        if read == 0 {
            return Err("incomplete request body".to_string());
        }
        data.extend_from_slice(&buffer[..read]);
        if data.len() > MAX_REQUEST_BYTES {
            return Err("request too large".to_string());
        }
    }

    let headers = String::from_utf8_lossy(&data[..header_end]);
    let first_line = headers.lines().next().ok_or("missing request line")?;
    let mut parts = first_line.split_whitespace();
    let method = parts.next().ok_or("missing method")?.to_string();
    let path = parts.next().ok_or("missing path")?.to_string();
    let body = data[body_start..body_start + content_length].to_vec();
    Ok(Request { method, path, body })
}

fn parse_content_length(headers: &str) -> Result<usize, String> {
    for line in headers.lines().skip(1) {
        if let Some((name, value)) = line.split_once(':') {
            if name.trim().eq_ignore_ascii_case("content-length") {
                return value.trim().parse().map_err(|_| "invalid content length".to_string());
            }
        }
    }
    Ok(0)
}

fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|window| window == needle)
}

fn write_response(stream: &mut TcpStream, status: u16, body: &str) {
    let reason = match status {
        200 => "OK",
        204 => "No Content",
        400 => "Bad Request",
        404 => "Not Found",
        422 => "Unprocessable Content",
        _ => "Error",
    };
    let response = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, POST, OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes());
    let _ = stream.flush();
}
