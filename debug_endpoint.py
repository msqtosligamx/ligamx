# PRUEBA SIMPLE - Agrega esto a tu servidor principal para verificar

# 1. Primero, agrega estos imports al inicio de tu archivo principal:
from flask import Flask, request, jsonify
import jwt

# 2. Agrega este endpoint de prueba para verificar que funciona:
@app.route('/api/test', methods=['GET'])
def test_endpoint():
    return jsonify({
        'message': 'Endpoint funciona',
        'server': 'Render',
        'status': 'OK'
    })

# 3. Agrega el endpoint de admin delete (versión simplificada):
@app.route('/api/admin/delete-seleccion', methods=['DELETE', 'OPTIONS'])
def delete_seleccion_simple():
    # Manejar CORS preflight
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        print("=== DEBUG: Endpoint llamado ===")
        
        # Obtener token del header
        auth_header = request.headers.get('Authorization')
        print(f"DEBUG: Auth header: {auth_header}")
        
        if not auth_header or not auth_header.startswith('Bearer '):
            print("DEBUG: No hay token válido")
            return jsonify({'error': 'Token no proporcionado'}), 401
        
        token = auth_header.split(' ')[1]
        print(f"DEBUG: Token recibido: {token[:20]}...")
        
        # Decodificar token
        try:
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            user_email = decoded_token.get('email')
            print(f"DEBUG: Email del token: {user_email}")
            
            if user_email != 'greenday_115@hotmail.com':
                print("DEBUG: No es admin")
                return jsonify({'error': 'No autorizado - Solo admin'}), 403
                
        except Exception as jwt_error:
            print(f"DEBUG: Error JWT: {jwt_error}")
            return jsonify({'error': 'Token inválido'}), 401
        
        # Obtener datos del body
        data = request.get_json()
        print(f"DEBUG: Body data: {data}")
        
        user_id = data.get('userId')
        jornada = data.get('jornada')
        
        if not user_id or not jornada:
            return jsonify({'error': 'Faltan userId y jornada'}), 400
        
        print(f"DEBUG: Intentando borrar userId={user_id}, jornada={jornada}")
        
        # Aquí iría el delete real
        # result = supabase_admin.table('selecciones').delete().eq('user_id', user_id).eq('jornada', jornada).execute()
        
        print("DEBUG: Operación completada")
        return jsonify({'success': True, 'message': 'Selección borrada correctamente'})
        
    except Exception as e:
        print(f"DEBUG: Error general: {e}")
        return jsonify({'error': f'Error del servidor: {str(e)}'}), 500

# 4. Agrega esto para registrar las rutas:
if __name__ == '__main__':
    print("=== DEBUG: Rutas registradas ===")
    for rule in app.url_map.iter_rules():
        print(f"{rule.methods} {rule.rule}")
    app.run(debug=True, port=5000)
