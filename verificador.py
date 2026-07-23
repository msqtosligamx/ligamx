import os
import sys
import argparse
import unicodedata
import difflib
import requests
from supabase import create_client, Client

# --- CONFIGURACIÓN ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError(
        "Faltan las variables de entorno SUPABASE_URL y/o SUPABASE_SERVICE_KEY."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

BASE_URL = "https://www.thesportsdb.com/api/v1/json/123"
LIGA_MX_ID = "4350"

# Overrides manuales para nombres cortos/alias que la API regresa a veces.
# (clave = como llega de la API, valor = nombre EXACTO en la tabla equipos_ligamx)
NORMALIZAR_NOMBRES = {
    'Mazatlán':             'Mazatlan',
    'León':                 'Leon',
    'Querétaro':            'Queretaro',
    'Querétaro FC':         'Queretaro FC',
    'FC Juárez':            'FC Juarez',
    'Juárez':               'FC Juarez',
    'Juarez':               'FC Juarez',
    'Atlético de San Luis': 'Atletico de San Luis',
    'Atletico de San Luis': 'Atletico de San Luis',
    'Atlético San Luis':    'Atletico de San Luis',
    'Atlético':             'Atletico de San Luis',
    'San Luis':             'Atletico de San Luis',
    'Tigres UANL':          'Tigres',
    'UANL':                 'Tigres',
    'Tigres':               'Tigres',
}

# Se llena en tiempo de ejecución con los nombres reales de la tabla equipos_ligamx
_NOMBRES_BD_CACHE = None


def _quitar_acentos(texto):
    """Convierte 'Atlético' -> 'Atletico', ignorando mayúsculas."""
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    return sin_acentos.strip().lower()


def _cargar_nombres_bd():
    """Trae y cachea los nombres reales de equipos_ligamx (una sola vez por corrida)."""
    global _NOMBRES_BD_CACHE
    if _NOMBRES_BD_CACHE is None:
        res = supabase.table("equipos_ligamx").select("id, nombre").execute()
        _NOMBRES_BD_CACHE = res.data or []
    return _NOMBRES_BD_CACHE


def normalizar_nombre(nombre):
    """
    Devuelve el nombre EXACTO como está guardado en equipos_ligamx.
    Orden de intentos:
      1. Override manual (NORMALIZAR_NOMBRES)
      2. Coincidencia exacta ignorando acentos/mayúsculas contra la BD
      3. Coincidencia difusa (fuzzy) contra la BD, con warning en consola
      4. Si nada funciona, regresa el nombre original tal cual llegó (y avisa)
    """
    if nombre in NORMALIZAR_NOMBRES:
        return NORMALIZAR_NOMBRES[nombre]

    equipos_bd = _cargar_nombres_bd()
    nombre_sin_acentos = _quitar_acentos(nombre)

    # Intento 2: match exacto ignorando acentos/mayúsculas
    for equipo in equipos_bd:
        if _quitar_acentos(equipo['nombre']) == nombre_sin_acentos:
            return equipo['nombre']

    # Intento 3: fuzzy match como último recurso
    nombres_bd = [e['nombre'] for e in equipos_bd]
    sugerencias = difflib.get_close_matches(nombre, nombres_bd, n=1, cutoff=0.6)
    if sugerencias:
        print(f"  ⚠️  '{nombre}' no coincide exactamente. Usando el más parecido: '{sugerencias[0]}'. "
              f"Verifica y agrega este alias a NORMALIZAR_NOMBRES si es correcto.")
        return sugerencias[0]

    print(f"  ⚠️  '{nombre}' no se pudo emparejar con NINGÚN equipo de la base de datos. "
          f"Revisa el nombre exacto en la API vs. la tabla equipos_ligamx.")
    return nombre


def obtener_jornada_mas_reciente(jornada_especifica=None):
    """
    Busca la jornada más reciente que tenga partidos terminados en 2026
    y que aún tenga selecciones pendientes en la base de datos.
    Así evitamos procesar dos veces la misma jornada.

    Si se proporciona jornada_especifica, usa esa jornada en lugar de buscar automáticamente.
    """
    # Si se proporcionó una jornada específica, usarla directamente
    if jornada_especifica:
        print(f"Procesando jornada específica: {jornada_especifica}")
        jornada = int(jornada_especifica)
        url = f"{BASE_URL}/eventsround.php?id={LIGA_MX_ID}&r={jornada}&s=2026-2027"
        try:
            response = requests.get(url, timeout=10)
            eventos = response.json().get('events', []) or []
        except Exception as e:
            print(f"  Error al consultar jornada {jornada}: {e}")
            return None

        # Filtrar solo partidos de 2026
        eventos_2026 = [e for e in eventos if e.get('dateEvent', '').startswith('2026')]

        if not eventos_2026:
            print(f"  Jornada {jornada}: sin partidos de 2026.")
            return None

        print(f"  Jornada {jornada}: {len(eventos_2026)} partidos encontrados")
        return jornada, eventos_2026

    # Buscar selecciones pendientes y agrupar por jornada
    selecciones = supabase.table("selecciones") \
        .select("jornada") \
        .eq("estatus", "pendiente") \
        .execute()

    # Obtener todas las jornadas que ya tienen selecciones (cualquier estatus)
    todas_selecciones = supabase.table("selecciones") \
        .select("jornada") \
        .execute()

    jornadas_con_selecciones = set(s['jornada'] for s in todas_selecciones.data) if todas_selecciones.data else set()
    print(f"Jornadas con selecciones: {sorted(jornadas_con_selecciones)}")

    if not selecciones.data:
        print("No hay selecciones pendientes que procesar.")
        # Si no hay selecciones pendientes, buscar jornadas sin selecciones que ya terminaron
        print("Buscando jornadas sin selecciones que ya terminaron...")
        jornadas_sin_seleccion = []
        for jornada in range(1, 18):  # Jornadas 1-17
            if jornada not in jornadas_con_selecciones:
                jornadas_sin_seleccion.append(jornada)

        if not jornadas_sin_seleccion:
            print("No hay jornadas sin selecciones.")
            return None

        # Revisar cada jornada sin selección y ver si ya terminaron sus partidos
        for jornada in jornadas_sin_seleccion:
            print(f"Revisando jornada {jornada} (sin selecciones)...")
            url = f"{BASE_URL}/eventsround.php?id={LIGA_MX_ID}&r={jornada}&s=2026-2027"
            try:
                response = requests.get(url, timeout=10)
                eventos = response.json().get('events', []) or []
            except Exception as e:
                print(f"  Error al consultar jornada {jornada}: {e}")
                continue

            # Filtrar solo partidos de 2026
            eventos_2026 = [e for e in eventos if e.get('dateEvent', '').startswith('2026')]

            if not eventos_2026:
                print(f"  Jornada {jornada}: sin partidos de 2026, saltando.")
                continue

            # Verificar si todos los partidos de la jornada ya terminaron
            terminados = [e for e in eventos_2026 if e.get('intHomeScore') not in (None, '')]

            if len(terminados) == len(eventos_2026) and len(terminados) > 0:
                print(f"  Jornada {jornada}: todos los partidos terminados ({len(terminados)}/{len(eventos_2026)})")
                return jornada, eventos_2026
            else:
                print(f"  Jornada {jornada}: {len(terminados)}/{len(eventos_2026)} partidos terminados, aún no se procesa.")

        print("Ninguna jornada sin selección tiene todos los partidos terminados.")
        return None

    # Obtener jornadas únicas pendientes ordenadas de menor a mayor
    jornadas_pendientes = sorted(set(s['jornada'] for s in selecciones.data))
    print(f"Jornadas con selecciones pendientes: {jornadas_pendientes}")

    # Solo procesar jornadas del Clausura 2026 (jornada 1 en adelante)
    # Ignorar jornadas con datos basura del Apertura
    jornadas_pendientes = [j for j in jornadas_pendientes if j >= 1]

    if not jornadas_pendientes:
        print("No hay jornadas válidas del Clausura pendientes.")
        return None

    # Revisar cada jornada pendiente y ver si ya terminaron sus partidos
    for jornada in jornadas_pendientes:
        print(f"Revisando jornada {jornada}...")
        url = f"{BASE_URL}/eventsround.php?id={LIGA_MX_ID}&r={jornada}&s=2026-2027"
        try:
            response = requests.get(url, timeout=10)
            eventos = response.json().get('events', []) or []
        except Exception as e:
            print(f"  Error al consultar jornada {jornada}: {e}")
            continue

        # Filtrar solo partidos de 2026 (Clausura)
        eventos_2026 = [e for e in eventos if e.get('dateEvent', '').startswith('2026')]

        if not eventos_2026:
            print(f"  Jornada {jornada}: sin partidos de 2026, saltando.")
            continue

        # Verificar si todos los partidos de la jornada ya terminaron
        terminados = [e for e in eventos_2026 if e.get('intHomeScore') not in (None, '')]

        if len(terminados) == len(eventos_2026) and len(terminados) > 0:
            print(f"  Jornada {jornada}: todos los partidos terminados ({len(terminados)}/{len(eventos_2026)})")
            return jornada, eventos_2026
        else:
            print(f"  Jornada {jornada}: {len(terminados)}/{len(eventos_2026)} partidos terminados, aún no se procesa.")

    print("Ninguna jornada pendiente tiene todos los partidos terminados.")
    return None


def obtener_perdedores_de_jornada(eventos):
    """Analiza los eventos y devuelve lista de equipos perdedores."""
    perdedores = []

    for p in eventos:
        goles_local  = p.get('intHomeScore')
        goles_visita = p.get('intAwayScore')

        if goles_local is None or goles_local == '':
            continue

        goles_local  = int(goles_local)
        goles_visita = int(goles_visita)
        local  = normalizar_nombre(p.get('strHomeTeam', ''))
        visita = normalizar_nombre(p.get('strAwayTeam', ''))

        print(f"  Partido: {local} {goles_local} - {goles_visita} {visita}")

        if goles_local < goles_visita:
            perdedores.append(local)
        elif goles_visita < goles_local:
            perdedores.append(visita)
        # Empate: nadie pierde vida

    return list(set(perdedores))


    print(f"EQUIPOS PENDIENTES DE SELECCIÓN - Usuario {user_id_en_sesion}")
    print("=" * 60)
    
    # Obtener todos los equipos de Liga MX
    todos_equipos = supabase.table("equipos_ligamx") \
        .select("id, nombre") \
        .order("nombre") \
        .execute()
    
    if not todos_equipos.data:
        print("No hay equipos registrados en la base de datos.")
        return
    
    # Obtener selecciones del usuario
    if jornada_actual is not None:
        # Para una jornada específica
        selecciones_usuario = supabase.table("selecciones") \
            .select("equipo_id, jornada") \
            .eq("user_id", user_id_en_sesion) \
            .eq("jornada", jornada_actual) \
            .neq("estatus", "fallo") \
            .execute()
        
        equipos_seleccionados_ids = {s['equipo_id'] for s in selecciones_usuario.data if s['equipo_id']}
        
        # Filtrar equipos no seleccionados en esta jornada
        equipos_pendientes = [
            equipo for equipo in todos_equipos.data 
            if equipo['id'] not in equipos_seleccionados_ids
        ]
        
        print(f"\nJornada {jornada_actual}:")
        if equipos_pendientes:
            tabla_datos = [
                [idx + 1, equipo['nombre']] 
                for idx, equipo in enumerate(equipos_pendientes)
            ]
            print(tabulate(tabla_datos, headers=["#", "Equipo"], tablefmt="grid"))
        else:
            print("Ya has seleccionado un equipo para esta jornada.")
            
    else:
        # Para todas las jornadas pendientes
        selecciones_usuario = supabase.table("selecciones") \
            .select("equipo_id, jornada, estatus") \
            .eq("user_id", user_id_en_sesion) \
            .neq("estatus", "fallo") \
            .execute()
        
        # Agrupar selecciones por jornada
        selecciones_por_jornada = {}
        for sel in selecciones_usuario.data:
            jornada = sel['jornada']
            if jornada not in selecciones_por_jornada:
                selecciones_por_jornada[jornada] = []
            if sel['equipo_id']:
                selecciones_por_jornada[jornada].append(sel['equipo_id'])
        
        # Mostrar pendientes por jornada
        for jornada in sorted(selecciones_por_jornada.keys()):
            equipos_seleccionados_ids = set(selecciones_por_jornada[jornada])
            equipos_pendientes = [
                equipo for equipo in todos_equipos.data 
                if equipo['id'] not in equipos_seleccionados_ids
            ]
            
            print(f"\nJornada {jornada}:")
            if equipos_pendientes:
                tabla_datos = [
                    [idx + 1, equipo['nombre']] 
                    for idx, equipo in enumerate(equipos_pendientes[:10])  # Limitar a 10 por legibilidad
                ]
                print(tabulate(tabla_datos, headers=["#", "Equipo"], tablefmt="grid"))
                if len(equipos_pendientes) > 10:
                    print(f"... y {len(equipos_pendientes) - 10} equipos más")
            else:
                print("Ya has seleccionado un equipo para esta jornada.")
    
    print("\n" + "=" * 60)


def actualizar_vidas(jornada_especifica=None):
    print("=" * 50)
    print("Iniciando verificación de jornada...")
    print("=" * 50)

    # 1. Buscar la jornada más reciente con partidos terminados y selecciones pendientes
    resultado = obtener_jornada_mas_reciente(jornada_especifica)

    if not resultado:
        print("No hay jornadas listas para procesar.")
        return

    jornada, eventos = resultado
    print(f"\nProcesando Jornada {jornada}...\n")

    # 2. Obtener todos los perfiles activos
    todos_perfiles = supabase.table("perfiles") \
        .select("id, username, vidas") \
        .eq("eliminado", False) \
        .execute()
    todos_user_ids = set(p['id'] for p in todos_perfiles.data)
    usuarios_por_id = {p['id']: p['username'] for p in todos_perfiles.data}
    print(f"Total usuarios activos: {len(todos_user_ids)}")
    print(f"Usuarios activos: {[usuarios_por_id[uid] for uid in todos_user_ids]}")

    # 3. Obtener usuarios que SÍ escogieron en esta jornada (con equipo_id válido)
    selecciones_jornada = supabase.table("selecciones") \
        .select("user_id, equipo_id, equipos_ligamx(nombre)") \
        .eq("jornada", jornada) \
        .execute()
    print(f"Total selecciones para jornada {jornada}: {len(selecciones_jornada.data)}")
    print(f"Selecciones: {selecciones_jornada.data}")

    # Solo considerar usuarios que tienen un equipo_id válido (no null)
    users_con_seleccion = set(s['user_id'] for s in selecciones_jornada.data if s['equipo_id'] is not None)
    usuarios_con_seleccion_nombres = [usuarios_por_id[uid] for uid in users_con_seleccion]
    print(f"Usuarios con selección válida: {usuarios_con_seleccion_nombres}")

    # 4. Penalizar usuarios que NO escogieron equipo
    users_sin_seleccion = todos_user_ids - users_con_seleccion
    usuarios_sin_seleccion_nombres = [usuarios_por_id[uid] for uid in users_sin_seleccion]
    print(f"Usuarios sin selección: {usuarios_sin_seleccion_nombres}")
    for u_id in users_sin_seleccion:
        perfil = next(p for p in todos_perfiles.data if p['id'] == u_id)
        vidas_actuales = perfil['vidas']

        # Verificar si ya tiene un registro de fallo para esta jornada (evitar duplicados)
        fallo_existente = supabase.table("selecciones") \
            .select("id") \
            .eq("user_id", u_id) \
            .eq("jornada", jornada) \
            .eq("estatus", "fallo") \
            .execute()

        if fallo_existente.data:
            print(f"  {usuarios_por_id[u_id]} ya tiene registro de fallo para jornada {jornada}, saltando...")
            continue

        nuevas_vidas = max(0, vidas_actuales - 1)

        supabase.table("perfiles").update({
            "vidas": nuevas_vidas,
            "eliminado": nuevas_vidas == 0
        }).eq("id", u_id).execute()

        # Insertar fila con estatus 'fallo' para que se pinte rojo en la tabla
        supabase.table("selecciones").insert({
            "user_id": u_id,
            "equipo_id": None,
            "jornada": jornada,
            "estatus": "fallo"
        }).execute()

        print(f"  {usuarios_por_id[u_id]} perdió una vida por no escoger equipo. Vidas: {nuevas_vidas}")

    # 5. Obtener perdedores de esa jornada
    equipos_que_perdieron = obtener_perdedores_de_jornada(eventos)

    if not equipos_que_perdieron:
        print("No hubo perdedores esta jornada (todos empataron).")
        supabase.table("selecciones") \
            .update({"estatus": "acierto"}) \
            .eq("jornada", jornada) \
            .eq("estatus", "pendiente") \
            .execute()
        return

    print(f"\nEquipos que perdieron en Jornada {jornada}: {equipos_que_perdieron}\n")

    # 6. Marcar como 'acierto' los que NO perdieron
    usuarios_fallaron = []
    for sel in selecciones_jornada.data:
        if sel.get('estatus') == 'fallo':
            continue
        # Saltar selecciones sin equipo_id (usuarios que no seleccionaron)
        if sel.get('equipo_id') is None:
            continue
        equipos_ligamx = sel.get('equipos_ligamx')
        nombre_equipo = equipos_ligamx.get('nombre', '') if equipos_ligamx else ''
        if nombre_equipo and nombre_equipo not in equipos_que_perdieron:
            supabase.table("selecciones") \
                .update({"estatus": "acierto"}) \
                .eq("user_id", sel['user_id']) \
                .eq("jornada", jornada) \
                .execute()
            print(f"  {usuarios_por_id[sel['user_id']]} acertó con {nombre_equipo}")

    # 7. Restar vidas a los que eligieron equipos perdedores
    usuarios_fallaron = []
    for nombre_equipo in equipos_que_perdieron:
        res_equipo = supabase.table("equipos_ligamx") \
            .select("id") \
            .eq("nombre", nombre_equipo) \
            .execute()

        if not res_equipo.data:
            print(f"  Equipo '{nombre_equipo}' no encontrado en la base de datos.")
            continue

        id_equipo = res_equipo.data[0]['id']

        selecciones_perdedor = supabase.table("selecciones") \
            .select("user_id") \
            .eq("equipo_id", id_equipo) \
            .eq("jornada", jornada) \
            .eq("estatus", "pendiente") \
            .execute()

        for sel in selecciones_perdedor.data:
            u_id = sel['user_id']

            perfil = supabase.table("perfiles") \
                .select("vidas") \
                .eq("id", u_id) \
                .single() \
                .execute()

            vidas_actuales = perfil.data['vidas']
            nuevas_vidas = max(0, vidas_actuales - 1)

            supabase.table("perfiles").update({
                "vidas": nuevas_vidas,
                "eliminado": nuevas_vidas == 0
            }).eq("id", u_id).execute()

            supabase.table("selecciones") \
                .update({"estatus": "fallo"}) \
                .eq("user_id", u_id) \
                .eq("jornada", jornada) \
                .execute()

            usuarios_fallaron.append(usuarios_por_id[u_id])
            print(f"  {usuarios_por_id[u_id]} perdió una vida por {nombre_equipo}. Vidas: {nuevas_vidas}")

    print(f"\nJornada {jornada} procesada correctamente.")
    if usuarios_fallaron:
        print(f"Usuarios que fallaron en esta jornada: {usuarios_fallaron}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Verificador de jornadas Liga MX Survivor')
    parser.add_argument('--jornada', type=int, help='Número de jornada específica a verificar (1-17)')
    args = parser.parse_args()

    actualizar_vidas(args.jornada)