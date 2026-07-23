from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import requests
import time
from datetime import datetime, timedelta
import jwt
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)  # Permitir llamadas desde el frontend

# Configuración Supabase con SERVICE ROLE KEY.
# Estas dos llaves YA NO están escritas aquí. Se leen desde variables de entorno
# que configuras en Render (Settings -> Environment). Si por alguna razón no
# existen (por ejemplo corriendo en tu compu sin configurarlas), el programa
# se detiene con un mensaje claro en vez de fallar de forma rara más adelante.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError(
        "Faltan las variables de entorno SUPABASE_URL y/o SUPABASE_SERVICE_KEY. "
        "Configúralas en Render (o en tu archivo .env local) antes de correr la app."
    )

supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def safe_error_response(error, status_code=503):
    """Devuelve un mensaje amigable para errores de red/servicio."""
    raw_message = str(error).lower()
    network_like = [
        "fetch",
        "network",
        "connection",
        "timeout",
        "temporarily unavailable",
        "name resolution",
    ]

    if any(token in raw_message for token in network_like):
        return jsonify({
            "success": False,
            "error": "Servicio temporalmente no disponible. Intenta de nuevo en unos segundos."
        }), status_code

    return jsonify({
        "success": False,
        "error": "No se pudo completar la solicitud."
    }), 500


@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def login_user():
    """Inicio de sesión de usuario"""
    if request.method == 'OPTIONS':
        return '', 200

    try:
        payload = request.get_json() or {}
        email = (payload.get('email') or '').strip().lower()
        password = payload.get('password') or ''

        if not email or not password:
            return jsonify({"success": False, "error": "Email y contraseña son requeridos"}), 400

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                result = supabase_admin.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })

                user = getattr(result, "user", None)
                session = getattr(result, "session", None)
                
                if user and session:
                    # Crear token JWT con información del usuario
                    token_payload = {
                        "email": user.email,
                        "user_id": user.id,
                        "exp": datetime.utcnow() + timedelta(hours=24)
                    }
                    token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")
                    
                    return jsonify({
                        "success": True,
                        "message": "Sesión iniciada correctamente",
                        "user": {
                            "id": user.id,
                            "email": user.email
                        },
                        "token": token,
                        "session_token": session.access_token
                    }), 200

                # Si no hubo excepción pero tampoco user, lo tratamos como error controlado
                return jsonify({
                    "success": False,
                    "error": "Credenciales incorrectas"
                }), 401

            except Exception as login_error:
                if attempt == max_attempts:
                    return safe_error_response(login_error)
                # Backoff pequeño para errores transitorios
                time.sleep(0.8 * attempt)

    except Exception as e:
        return safe_error_response(e)

@app.route('/api/auth/register', methods=['POST', 'OPTIONS'])
def register_user():
    """Registro de usuario con reintentos para evitar errores transitorios."""
    if request.method == 'OPTIONS':
        return '', 200

    try:
        payload = request.get_json() or {}
        email = (payload.get('email') or '').strip().lower()
        password = payload.get('password') or ''

        if not email or not password:
            return jsonify({"success": False, "error": "Email y contrasena son requeridos"}), 400

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                result = supabase_admin.auth.sign_up({
                    "email": email,
                    "password": password
                })

                user = getattr(result, "user", None)
                if user:
                    try:
                        supabase_admin.table('perfiles').insert({
                            "id": user.id,
                            "username": email,
                            "vidas": 3,
                            "eliminado": False
                        }).execute()
                    except Exception:
                        pass  # perfil ya existe; no bloquea el registro

                    return jsonify({
                        "success": True,
                        "message": "Cuenta creada correctamente",
                        "user_id": user.id
                    }), 201

                # Si no hubo excepción pero tampoco user, lo tratamos como error controlado
                return jsonify({
                    "success": False,
                    "error": "No se pudo crear la cuenta en este momento"
                }), 502

            except Exception as register_error:
                if attempt == max_attempts:
                    # Mostrar el error específico de Supabase
                    error_msg = str(register_error)
                    if "already registered" in error_msg.lower() or "user already exists" in error_msg.lower():
                        return jsonify({
                            "success": False,
                            "error": "Este correo ya está registrado. Inicia sesión en su lugar."
                        }), 400
                    elif "password" in error_msg.lower():
                        return jsonify({
                            "success": False,
                            "error": "La contraseña debe tener al menos 6 caracteres."
                        }), 400
                    elif "email" in error_msg.lower():
                        return jsonify({
                            "success": False,
                            "error": "El formato del correo no es válido."
                        }), 400
                    else:
                        return safe_error_response(register_error)
                # Backoff pequeño para errores transitorios
                time.sleep(0.8 * attempt)

    except Exception as e:
        return safe_error_response(e)

LIGA_MX_ID = "4350"  # id de "Mexican Primera League" en TheSportsDB
THESPORTSDB_KEY = os.environ.get("THESPORTSDB_KEY", "123")  # "123" es la key gratuita pública, no es secreta
THESPORTSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_KEY}"

# Secreto para firmar los tokens JWT de sesión. También sale de una variable
# de entorno. Si alguien conociera este valor podría fabricar tokens falsos
# y hacerse pasar por cualquier usuario, así que nunca debe ir escrito en el código.
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "Falta la variable de entorno JWT_SECRET. Configúrala en Render (o en tu .env local)."
    )

# Correo del único usuario que puede usar los endpoints de admin.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "greenday_115@hotmail.com")


@app.route('/api/calendario-ligamx')
def obtener_calendario():
    """
    Endpoint para obtener el calendario de la próxima jornada de Liga MX.

    Estrategia (sin hardcodear temporada ni jornada):
      1. Pedimos a TheSportsDB los próximos partidos de la liga
         (eventsnextleague.php) para saber cuál es la jornada y
         temporada que sigue.
      2. Con esa jornada y temporada, pedimos el listado completo
         de esa jornada (eventsround.php) para regresar todos sus
         partidos, no solo los primeros.
    """
    try:
        # 1. Próximos partidos (para detectar jornada y temporada actuales)
        url_next = f"{THESPORTSDB_BASE}/eventsnextleague.php"
        resp_next = requests.get(url_next, params={"id": LIGA_MX_ID}, timeout=10)
        resp_next.raise_for_status()
        proximos = resp_next.json().get("events") or []

        if not proximos:
            return jsonify({
                "success": False,
                "error": "TheSportsDB no tiene partidos próximos cargados todavía."
            }), 502

        jornada = proximos[0]["intRound"]
        temporada = proximos[0]["strSeason"]

        # 2. Todos los partidos de esa jornada
        url_round = f"{THESPORTSDB_BASE}/eventsround.php"
        resp_round = requests.get(
            url_round,
            params={"id": LIGA_MX_ID, "r": jornada, "s": temporada},
            timeout=10,
        )
        resp_round.raise_for_status()
        partidos = resp_round.json().get("events") or proximos

        return jsonify({
            "success": True,
            "jornada": jornada,
            "temporada": temporada,
            "partidos": partidos
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "error": f"No se pudo consultar TheSportsDB: {e}"
        }), 503
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/calendario-jornada/<int:round>')
def obtener_jornada_especifica(round):
    """
    Endpoint para obtener los partidos de una jornada específica.
    Sirve como proxy para evitar problemas de CORS en el frontend.
    """
    try:
        temporada = "2026-2027"  # Temporada actual
        url_round = f"{THESPORTSDB_BASE}/eventsround.php"
        resp_round = requests.get(
            url_round,
            params={"id": LIGA_MX_ID, "r": round, "s": temporada},
            timeout=10,
        )
        resp_round.raise_for_status()
        partidos = resp_round.json().get("events") or []

        return jsonify({
            "success": True,
            "round": round,
            "temporada": temporada,
            "partidos": partidos
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "error": f"No se pudo consultar TheSportsDB: {e}"
        }), 503
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/calendario-temporada')
def obtener_temporada_completa():
    """
    Endpoint para obtener TODOS los partidos de la temporada en una sola llamada.
    Esto evita el rate limiting de TheSportsDB cuando se detecta la jornada actual.
    """
    try:
        temporada = "2026-2027"  # Temporada actual
        url_season = f"{THESPORTSDB_BASE}/eventsseason.php"
        resp_season = requests.get(
            url_season,
            params={"id": LIGA_MX_ID, "s": temporada},
            timeout=10,
        )
        resp_season.raise_for_status()
        partidos = resp_season.json().get("events") or []

        return jsonify({
            "success": True,
            "temporada": temporada,
            "partidos": partidos
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "error": f"No se pudo consultar TheSportsDB: {e}"
        }), 503
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/admin/delete-seleccion', methods=['DELETE', 'OPTIONS'])
def delete_seleccion():
    """Endpoint para que el admin borre selecciones de usuarios"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Obtener token del header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Token no proporcionado'}), 401
        
        token = auth_header.split(' ')[1]
        
        # Decodificar token JWT para obtener email
        try:
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            user_email = decoded_token.get('email')
            
            if user_email != ADMIN_EMAIL:
                return jsonify({'error': 'No autorizado - Solo admin'}), 403
                
        except Exception as jwt_error:
            return jsonify({'error': 'Token inválido'}), 401
        
        # Obtener datos del body
        data = request.get_json()
        user_id = data.get('userId')
        jornada = data.get('jornada')
        
        if not user_id or not jornada:
            return jsonify({'error': 'Faltan userId y jornada'}), 400
        
        # Ejecutar delete con service role key
        result = supabase_admin.table('selecciones').delete().eq('user_id', user_id).eq('jornada', jornada).execute()
        
        if hasattr(result, 'error') and result.error:
            return jsonify({'error': str(result.error)}), 500
        
        return jsonify({'success': True, 'message': 'Selección borrada correctamente'})
        
    except Exception as e:
        return jsonify({'error': f'Error del servidor: {str(e)}'}), 500

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """Endpoint de prueba para verificar que el servidor funciona"""
    return jsonify({
        'message': 'Endpoint funciona',
        'server': 'Render',
        'status': 'OK',
        'routes': [str(rule) for rule in app.url_map.iter_rules()]
    })

@app.route('/api/admin/reset-tournament', methods=['DELETE', 'OPTIONS'])
def reset_tournament():
    """Endpoint para borrar todas las tablas y empezar el torneo en ceros"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Obtener token del header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Token no proporcionado'}), 401
        
        token = auth_header.split(' ')[1]
        
        # Decodificar token JWT para obtener email
        try:
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            user_email = decoded_token.get('email')
            
            if user_email != ADMIN_EMAIL:
                return jsonify({'error': 'No autorizado - Solo admin'}), 403
                
        except Exception as jwt_error:
            return jsonify({'error': 'Token inválido'}), 401
        
        # Lista de tablas a borrar (en orden correcto para evitar conflictos de FK)
        tablas = [
            'selecciones',
            'resultados',
            'jornadas',
            'equipos',
            'usuarios'
        ]
        
        resultados = {}
        
        # Borrar cada tabla
        for tabla in tablas:
            try:
                if tabla == 'usuarios':
                    # No borrar al admin principal
                    result = supabase_admin.table(tabla).delete().neq('email', ADMIN_EMAIL).execute()
                    resultados[tabla] = "Borrada (admin conservado)"
                else:
                    result = supabase_admin.table(tabla).delete().neq('id', 0).execute()
                    resultados[tabla] = "Borrada correctamente"
                    
                if hasattr(result, 'error') and result.error:
                    resultados[tabla] = f"Error: {str(result.error)}"
                    
            except Exception as e:
                resultados[tabla] = f"Error: {str(e)}"
        
        return jsonify({
            'success': True,
            'message': 'Torneo reseteado correctamente',
            'resultados': resultados
        })
        
    except Exception as e:
        return jsonify({'error': f'Error del servidor: {str(e)}'}), 500

@app.route('/api/verificar', methods=['POST'])
def verificar_jornada():
    """Endpoint para correr el verificador manualmente desde el panel admin"""
    try:
        import subprocess
        jornada_especifica = request.args.get('jornada')

        cmd = ['python', 'verificador.py']
        if jornada_especifica:
            cmd.append('--jornada')
            cmd.append(jornada_especifica)

        resultado = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=60
        )
        if resultado.returncode == 0:
            return jsonify({
                "success": True,
                "mensaje": "Verificacion completada. " + resultado.stdout[-200:].strip()
            })
        else:
            return jsonify({
                "success": False,
                "error": resultado.stderr[-300:].strip()
            }), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# Endpoints para reemplazar el uso directo de Supabase en el frontend

@app.route('/api/user/perfil', methods=['GET', 'OPTIONS'])
def get_user_perfil():
    """Obtener el perfil del usuario autenticado"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Token no proporcionado'}), 401
        
        token = auth_header.split(' ')[1]
        
        # Decodificar token para obtener user_id
        try:
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            user_id = decoded_token.get('user_id')
        except Exception:
            return jsonify({'error': 'Token inválido'}), 401
        
        # Obtener perfil de Supabase
        result = supabase_admin.table('perfiles').select('*').eq('id', user_id).maybe_single().execute()
        
        if hasattr(result, 'error') and result.error:
            return jsonify({'error': str(result.error)}), 500
        
        return jsonify({'success': True, 'perfil': result.data})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/equipos', methods=['GET'])
def get_equipos():
    """Obtener todos los equipos disponibles"""
    try:
        result = supabase_admin.table('equipos_ligamx').select('*').execute()
        
        if hasattr(result, 'error') and result.error:
            return jsonify({'error': str(result.error)}), 500
        
        return jsonify({'success': True, 'equipos': result.data})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/selecciones', methods=['POST', 'OPTIONS'])
def save_seleccion():
    """Guardar una selección de equipo para una jornada"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Token no proporcionado'}), 401
        
        token = auth_header.split(' ')[1]
        
        try:
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            user_id = decoded_token.get('user_id')
        except Exception:
            return jsonify({'error': 'Token inválido'}), 401
        
        data = request.get_json()
        equipo_id = data.get('equipo_id')
        jornada = data.get('jornada')
        
        if not equipo_id or not jornada:
            return jsonify({'error': 'Faltan equipo_id y jornada'}), 400
        
        # Verificar si ya existe selección para esta jornada
        existing = supabase_admin.table('selecciones').select('*').eq('user_id', user_id).eq('jornada', jornada).maybe_single().execute()
        
        if existing.data:
            return jsonify({'error': 'Ya tienes una selección para esta jornada'}), 400
        
        # Insertar nueva selección
        result = supabase_admin.table('selecciones').insert({
            'user_id': user_id,
            'equipo_id': equipo_id,
            'jornada': jornada,
            'estatus': 'pendiente'
        }).execute()
        
        if hasattr(result, 'error') and result.error:
            return jsonify({'error': str(result.error)}), 500
        
        return jsonify({'success': True, 'message': 'Selección guardada correctamente'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/selecciones/user', methods=['GET', 'OPTIONS'])
def get_user_selecciones():
    """Obtener todas las selecciones del usuario autenticado"""
    if request.method == 'OPTIONS':
        return '', 200

    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Token no proporcionado'}), 401

        token = auth_header.split(' ')[1]

        try:
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            user_id = decoded_token.get('user_id')
        except Exception:
            return jsonify({'error': 'Token inválido'}), 401

        result = supabase_admin.table('selecciones').select('*').eq('user_id', user_id).execute()

        if hasattr(result, 'error') and result.error:
            return jsonify({'error': str(result.error)}), 500

        return jsonify({'success': True, 'selecciones': result.data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tabla-global', methods=['GET'])
def get_tabla_global():
    """Obtener la tabla global de supervivencia"""
    try:
        # Obtener perfiles
        perfiles_result = supabase_admin.table('perfiles').select('id, username, vidas').order('vidas', desc=True).execute()
        
        # Obtener selecciones con nombres de equipos
        selecciones_result = supabase_admin.table('selecciones').select('*, equipos_ligamx(nombre)').execute()
        
        if hasattr(perfiles_result, 'error') and perfiles_result.error:
            return jsonify({'error': str(perfiles_result.error)}), 500
        
        if hasattr(selecciones_result, 'error') and selecciones_result.error:
            return jsonify({'error': str(selecciones_result.error)}), 500
        
        return jsonify({
            'success': True,
            'perfiles': perfiles_result.data,
            'selecciones': selecciones_result.data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)